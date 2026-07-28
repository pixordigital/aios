"""Multi-LLM providers — OpenRouter, Ollama, OpenAI, Anthropic."""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import AsyncGenerator

import httpx

from aios.config import settings

logger = logging.getLogger(__name__)

# SSE event types for streaming
STREAM_TOKEN = "token"
STREAM_DONE = "done"
STREAM_ERROR = "error"
STREAM_TOOL_CALL = "tool_call"

# --- Retry / Circuit Breaker ---

_MAX_RETRIES = 3
_BASE_DELAY = 1.0

# circuit breaker per (provider_class, model): 0 = open, 1 = half-open, 2 = closed
_circuits: dict[str, dict] = {}
_CIRCUIT_TIMEOUT = 60.0  # seconds before half-open retry


def _circuit_key(provider_cls: type, model: str) -> str:
    return f"{provider_cls.__name__}:{model}"


def _circuit_allowed(key: str) -> bool:
    state = _circuit_state(key)
    if state["status"] == "open":
        if time.time() - state["last_failure"] > _CIRCUIT_TIMEOUT:
            state["status"] = "half-open"
            _circuits[key] = state
            return True
        return False
    return True


def _circuit_state(key: str) -> dict:
    if key not in _circuits:
        _circuits[key] = {"status": "closed", "failures": 0, "last_failure": 0.0}
    return _circuits[key]


def _circuit_record_failure(key: str):
    state = _circuit_state(key)
    state["failures"] += 1
    state["last_failure"] = time.time()
    if state["failures"] >= 3:
        state["status"] = "open"
        logger.warning("Circuit breaker OPEN for %s", key)


def _circuit_record_success(key: str):
    state = _circuit_state(key)
    state["failures"] = 0
    state["status"] = "closed"


_RETRYABLE_ERRORS = (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)


async def _retry(fn, provider_cls: type, model: str, *args, **kw):
    """Call fn with retry + circuit breaker."""
    ck = _circuit_key(provider_cls, model)
    if not _circuit_allowed(ck):
        raise LLMError(f"Circuit breaker open for {model}")

    last_err = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            result = await fn(*args, **kw)
            _circuit_record_success(ck)
            return result
        except LLMError:
            raise  # non-retryable (auth, 404)
        except _RETRYABLE_ERRORS as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning("Retry %d/%d for %s after %s: %.1fs", attempt+1, _MAX_RETRIES, model, type(e).__name__, delay)
                await asyncio.sleep(delay)
        except Exception as e:
            last_err = e
            if attempt < _MAX_RETRIES:
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning("Retry %d/%d for %s on unexpected error: %s", attempt+1, _MAX_RETRIES, model, e)
                await asyncio.sleep(delay)
    _circuit_record_failure(ck)
    raise LLMError(f"All {_MAX_RETRIES+1} retries failed for {model}: {last_err}")


# Fallback chain: model name → list of fallback models
_FALLBACK_CHAIN = {
    "openai/gpt-4o": ["openai/gpt-4o-mini", "anthropic-direct/claude-sonnet-4-20250514"],
    "anthropic-direct/claude-sonnet-4-20250514": ["openai/gpt-4o", "openai/gpt-4o-mini"],
}


def _fallback_models(model: str) -> list[str]:
    return _FALLBACK_CHAIN.get(model, [])


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str = "openai/gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        ...

    async def chat_stream(
        self,
        messages: list[dict],
        model: str = "openai/gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        result = await self.chat(messages, model, temperature, max_tokens, tools)
        content = result.get("content", "") or ""
        if content:
            yield {"type": STREAM_TOKEN, "content": content}
        if result.get("tool_calls"):
            yield {"type": STREAM_TOOL_CALL, "tool_calls": result["tool_calls"]}
        yield {"type": STREAM_DONE}

    async def chat_retry(self, *args, **kw) -> dict:
        """Call chat with retry + circuit breaker."""
        return await _retry(lambda: self.chat(*args, **kw), type(self), kw.get("model", "unknown"))

    async def chat_stream_retry(self, *args, **kw) -> AsyncGenerator[dict, None]:
        """Stream with retry on connection errors."""
        ck = _circuit_key(type(self), kw.get("model", "unknown"))
        if not _circuit_allowed(ck):
            yield {"type": STREAM_ERROR, "error": f"Circuit breaker open for {kw.get('model', 'unknown')}"}
            return
        started = False
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async for ev in self.chat_stream(*args, **kw):
                    started = True
                    yield ev
                _circuit_record_success(ck)
                return
            except _RETRYABLE_ERRORS as e:
                if attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY * (2 ** attempt)
                    logger.warning("Stream retry %d/%d after %s", attempt+1, _MAX_RETRIES, type(e).__name__)
                    await asyncio.sleep(delay)
                else:
                    _circuit_record_failure(ck)
                    yield {"type": STREAM_ERROR, "error": f"Stream failed after retries: {e}"}
                    return
            except Exception as e:
                yield {"type": STREAM_ERROR, "error": str(e)}
                return


def get_provider(model: str, api_key: str | None = None) -> LLMProvider:
    """Route to correct provider based on model name prefix."""
    if model.startswith("ollama/"):
        return OllamaProvider()
    elif model.startswith("opencode/"):
        return OpenRouterProvider(api_key)  # uses OpenRouter endpoint
    elif model.startswith("openai-direct/"):
        return OpenAIProvider(api_key)
    elif model.startswith("anthropic-direct/"):
        return AnthropicProvider(api_key)
    else:
        return OpenRouterProvider(api_key)


# ─── OpenRouter ───

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.openrouter_api_key

    async def chat(
        self,
        messages: list[dict],
        model: str = "openai/gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, 16384),
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/pixor/aios",
                },
                json=body,
            )
            if resp.status_code == 401:
                raise LLMError("OpenRouter auth failed")
            if resp.status_code == 429:
                raise LLMError("OpenRouter rate limited")
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]

    async def chat_stream(
        self,
        messages: list[dict],
        model: str = "openai/gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, 16384),
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/pixor/aios",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    if resp.status_code == 401:
                        yield {"type": STREAM_ERROR, "error": "OpenRouter auth failed"}
                    elif resp.status_code == 429:
                        yield {"type": STREAM_ERROR, "error": "OpenRouter rate limited"}
                    else:
                        yield {"type": STREAM_ERROR, "error": f"HTTP {resp.status_code}: {text[:200]}"}
                    return

                content_parts = []
                tool_calls_acc = {}
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        yield {"type": STREAM_TOKEN, "content": delta["content"]}

                    tc = delta.get("tool_calls")
                    if tc:
                        for tcc in tc:
                            idx = tcc.get("index", 0)
                            if idx not in tool_calls_acc:
                                fn = tcc.get("function", {})
                                tool_calls_acc[idx] = {
                                    "id": tcc.get("id", f"call_{idx}"),
                                    "type": "function",
                                    "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", "")},
                                }
                            else:
                                fn = tcc.get("function", {})
                                tool_calls_acc[idx]["function"]["arguments"] += fn.get("arguments", "")

                if tool_calls_acc:
                    tcs = [v for _, v in sorted(tool_calls_acc.items())]
                    yield {"type": STREAM_TOOL_CALL, "tool_calls": tcs}

                yield {"type": STREAM_DONE}


# ─── OpenAI (direct) ───

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.openai_api_key

    async def chat(
        self,
        messages: list[dict],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, 16384),
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if resp.status_code == 401:
                raise LLMError("OpenAI auth failed")
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]

    async def chat_stream(
        self,
        messages: list[dict],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, 16384),
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield {"type": STREAM_ERROR, "error": f"OpenAI HTTP {resp.status_code}: {text[:200]}"}
                    return

                content_parts = []
                tool_calls_acc = {}
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                        yield {"type": STREAM_TOKEN, "content": delta["content"]}

                    tc = delta.get("tool_calls")
                    if tc:
                        for tcc in tc:
                            idx = tcc.get("index", 0)
                            if idx not in tool_calls_acc:
                                fn = tcc.get("function", {})
                                tool_calls_acc[idx] = {
                                    "id": tcc.get("id", f"call_{idx}"),
                                    "type": "function",
                                    "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", "")},
                                }
                            else:
                                fn = tcc.get("function", {})
                                tool_calls_acc[idx]["function"]["arguments"] += fn.get("arguments", "")

                if tool_calls_acc:
                    tcs = [v for _, v in sorted(tool_calls_acc.items())]
                    yield {"type": STREAM_TOOL_CALL, "tool_calls": tcs}

                yield {"type": STREAM_DONE}


# ─── Anthropic (direct) ───

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.anthropic_api_key

    @staticmethod
    def _to_anthropic_msgs(messages: list[dict]) -> tuple[str, list[dict]]:
        system = ""
        anthropic_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            elif m["role"] == "user":
                anthropic_messages.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                anthro = {"role": "assistant", "content": m.get("content", "")}
                if m.get("tool_calls"):
                    anthropic_messages.append(anthro)
                    for tc in m["tool_calls"]:
                        fn = tc.get("function", {})
                        anthropic_messages.append({
                            "role": "assistant",
                            "content": f"Tool use: {fn.get('name', '')}({fn.get('arguments', '')})"
                        })
                else:
                    anthropic_messages.append(anthro)
            elif m["role"] == "tool":
                anthropic_messages.append({"role": "user", "content": f"Tool result: {m['content']}"})
        return system, anthropic_messages

    @staticmethod
    def _to_openai_tools(tools: list[dict] | None) -> list[dict] | None:
        if not tools:
            return None
        return [{
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": t["function"].get("parameters", {}),
        } for t in tools]

    async def chat(
        self,
        messages: list[dict],
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        system, anthropic_messages = self._to_anthropic_msgs(messages)
        body = {
            "model": model,
            "max_tokens": min(max_tokens, 16384),
            "messages": anthropic_messages,
        }
        if system:
            body["system"] = system
        anthro_tools = self._to_openai_tools(tools)
        if anthro_tools:
            body["tools"] = anthro_tools
        if tool_choice:
            # anthropic uses {type: "tool", name: "..."} format
            if isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                body["tool_choice"] = {"type": "tool", "name": tool_choice["function"]["name"]}
            else:
                body["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if resp.status_code == 401:
                raise LLMError("Anthropic auth failed")
            resp.raise_for_status()
            data = resp.json()

            choice = {"role": "assistant", "content": ""}
            for block in data.get("content", []):
                if block["type"] == "text":
                    choice["content"] = block["text"]
                elif block["type"] == "tool_use":
                    if "tool_calls" not in choice:
                        choice["tool_calls"] = []
                    choice["tool_calls"].append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": str(block.get("input", {})),
                        },
                    })
            return choice

    async def chat_stream(
        self,
        messages: list[dict],
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        system, anthropic_messages = self._to_anthropic_msgs(messages)
        body = {
            "model": model,
            "max_tokens": min(max_tokens, 16384),
            "messages": anthropic_messages,
            "stream": True,
        }
        if system:
            body["system"] = system
        anthro_tools = self._to_openai_tools(tools)
        if anthro_tools:
            body["tools"] = anthro_tools

        content_acc = []
        current_tool = None

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield {"type": STREAM_ERROR, "error": f"Anthropic HTTP {resp.status_code}: {text[:200]}"}
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type", "")
                    if etype == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool = {
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "input": "",
                            }
                    elif etype == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            content_acc.append(text)
                            yield {"type": STREAM_TOKEN, "content": text}
                        elif delta.get("type") == "input_json_delta":
                            if current_tool:
                                current_tool["input"] += delta.get("partial_json", "")
                    elif etype == "content_block_stop" and current_tool:
                        tool_calls = [{
                            "id": current_tool["id"],
                            "type": "function",
                            "function": {
                                "name": current_tool["name"],
                                "arguments": current_tool["input"],
                            },
                        }]
                        yield {"type": STREAM_TOOL_CALL, "tool_calls": tool_calls}
                        current_tool = None

                yield {"type": STREAM_DONE}


# ─── Ollama (local) ───

class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    async def chat(
        self,
        messages: list[dict],
        model: str = "llama3",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        raw_model = model.removeprefix("ollama/")
        body = {
            "model": raw_model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": min(max_tokens, 32768),
            },
            "stream": False,
        }
        if tools:
            body["tools"] = [t["function"] for t in tools]
        if tool_choice:
            body["tool_choice"] = tool_choice

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=body,
            )
            if resp.status_code == 404:
                raise LLMError(f"Ollama model '{raw_model}' not found. Run: ollama pull {raw_model}")
            resp.raise_for_status()
            data = resp.json()

            choice = {"role": "assistant", "content": data.get("message", {}).get("content", "")}
            if data.get("message", {}).get("tool_calls"):
                choice["tool_calls"] = [{
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": str(tc["function"]["arguments"]),
                    },
                } for i, tc in enumerate(data["message"]["tool_calls"])]
            return choice

    async def chat_stream(
        self,
        messages: list[dict],
        model: str = "llama3",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        raw_model = model.removeprefix("ollama/")
        body = {
            "model": raw_model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": min(max_tokens, 32768),
            },
            "stream": True,
        }
        if tools:
            body["tools"] = [t["function"] for t in tools]

        tool_calls_acc = {}
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=body,
            ) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield {"type": STREAM_ERROR, "error": f"Ollama HTTP {resp.status_code}: {text[:200]}"}
                    return

                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = chunk.get("message", {})
                    if msg.get("content"):
                        yield {"type": STREAM_TOKEN, "content": msg["content"]}
                    if msg.get("tool_calls"):
                        for i, tc in enumerate(msg["tool_calls"]):
                            tool_calls_acc[i] = {
                                "id": f"call_{i}",
                                "type": "function",
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": str(tc["function"]["arguments"]),
                                },
                            }
                    if chunk.get("done"):
                        break

                if tool_calls_acc:
                    tcs = [v for _, v in sorted(tool_calls_acc.items())]
                    yield {"type": STREAM_TOOL_CALL, "tool_calls": tcs}

                yield {"type": STREAM_DONE}


class LLMError(Exception):
    pass
