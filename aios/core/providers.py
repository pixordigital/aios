"""Multi-LLM providers — OpenRouter, Ollama, OpenAI, Anthropic."""

import logging
from abc import ABC, abstractmethod

import httpx

from aios.config import settings

logger = logging.getLogger(__name__)


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
    ) -> dict:
        ...


def get_provider(model: str, api_key: str | None = None) -> LLMProvider:
    """Route to correct provider based on model name prefix.

    Prefix rules:
      ollama/...       → local Ollama
      openai-direct/... → OpenAI API directly
      anthropic-direct/... → Anthropic API directly
      openrouter/...    → OpenRouter (explicit)
      everything else   → OpenRouter (default)
    """
    if model.startswith("ollama/"):
        return OllamaProvider()
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
    ) -> dict:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, 16384),
        }
        if tools:
            body["tools"] = tools

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
    ) -> dict:
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, 16384),
        }
        if tools:
            body["tools"] = tools

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


# ─── Anthropic (direct) ───

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.anthropic_api_key

    async def chat(
        self,
        messages: list[dict],
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> dict:
        # Convert OpenAI-style messages to Anthropic format
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
                    anthro["content"] = m.get("content") or ""
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

        body = {
            "model": model,
            "max_tokens": min(max_tokens, 16384),
            "messages": anthropic_messages,
        }
        if system:
            body["system"] = system
        if tools:
            # Convert to Anthropic tool format
            body["tools"] = [{
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {}),
            } for t in tools]

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

            # Convert Anthropic response back to OpenAI format
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
    ) -> dict:
        # Strip "ollama/" prefix from model name
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


class LLMError(Exception):
    pass
