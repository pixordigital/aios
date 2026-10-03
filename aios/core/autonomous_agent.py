"""Autonomous Agent — 100% autônomo com HITL se necessário.

Implementa ReAct + Reflexion (Shinn et al. 2023) + U-Mem dual-buffer.
Loop: Thought → Action (tool) → Observation → Evaluator → Reflection → Retry (max 3 trials)
Custo zero (verbal, sem fine-tuning). HITL apenas quando necessário.

Referências: Reflexion, ReAct, ReflAct, ELL, U-Mem, Agentic Memory
"""

import asyncio
import json
import logging
from typing import Dict, List

from aios.core.agent import AgentRuntime
from aios.core.agent_events import emit_trial_event
from aios.core.providers import STREAM_TOKEN, STREAM_TOOL_CALL
from aios.db.models import Agent as AgentModel

logger = logging.getLogger(__name__)

MAX_TRIALS = 3
HITL_VALUE_THRESHOLD = 5000  # R$5k
HITL_CONFIDENCE_THRESHOLD = 0.4


class Evaluator:
    """Heurística para detectar falha sem ground truth."""

    def evaluate(self, trajectory: List[dict], response: str, tool_calls: List[dict] | None) -> Dict:
        """Retorna {success: bool, reason: str, confidence: float}."""
        text = (response or "").lower()

        # Caso 1: alucinação — prometeu valor sem chamar tool de cálculo
        if any(kw in text for kw in ["r$ 10k", "r$10k", "preço 10k"]) and not tool_calls:
            return {"success": False, "reason": "Alucinação: prometeu valor sem consultar tool calculator/crm", "confidence": 0.2}

        # Caso 2: ineficiente — 3+ turns sem tool quando deveria chamar
        if len(trajectory) >= 6 and not tool_calls:
            # Se deveria ter chamado lead_score/calculator mas não chamou
            if "tá caro" in text or "caro" in str(trajectory).lower():
                return {"success": False, "reason": "Ineficiente: não chamou tool para objeção de preço", "confidence": 0.3}

        # Caso 3: resposta vazia ou genérica
        if not response or len(response.strip()) < 20:
            return {"success": False, "reason": "Resposta vazia ou muito curta", "confidence": 0.1}

        # Caso 4: tool error
        if tool_calls and any("Tool error" in str(t) for t in tool_calls):
            return {"success": False, "reason": "Tool error", "confidence": 0.2}

        # Caso 5: sem próxima ação quando deveria oferecer
        if "tá caro" in str(trajectory).lower() and "agendar" not in text and "reunião" not in text and "calcular" not in text:
            return {"success": False, "reason": "Objeção não contornada: sem oferecer próxima ação (agendamento/ROI)", "confidence": 0.3}

        # Caso 6: STT low confidence (voz) — "tacaro", texto muito curto, sem espaços
        # Heurística para Whisper/Kokoro STT errors
        trajectory_str = str(trajectory).lower()
        user_text = str(trajectory[-1].get("response", "") if trajectory else "") + " " + text
        # Detecta STT errors comuns
        if any(err in user_text for err in ["tacaro", "ta caro", "to caro"]) and "tá caro" not in user_text:
            return {"success": False, "reason": "STT: possível erro de transcrição (tacaro vs tá caro), pedir para repetir", "confidence": 0.2}
        if len(text.strip()) > 0 and len(text.strip()) < 4 and text.strip().lower() not in ["oi", "ok", "sim", "não", "ola"]:
            return {"success": False, "reason": "STT: texto muito curto, possível erro de transcrição, pedir para repetir", "confidence": 0.2}

        # Caso 7: fora da janela 24h (131047) — precisa template
        if "131047" in str(trajectory).lower() or "131047" in text or "outside 24h" in trajectory_str or "window" in trajectory_str and "template" in text:
            return {"success": False, "reason": "Fora da janela 24h (131047) — trocar para template aios_reengajamento_1 (Utility, pt_BR) com params [nome, empresa, assunto]", "confidence": 0.2}
        if "template" in trajectory_str and "131047" in str(trajectory):
            return {"success": False, "reason": "Template 131047 — usar whatsapp_template com aios_reengajamento_1", "confidence": 0.2}

        return {"success": True, "reason": "ok", "confidence": 0.85}


# The reflection prompt is a fixed boilerplate plus a trajectory truncated to
# 3000 chars and a failure reason, so its size is bounded and known: ~4k chars,
# or ~1k tokens at the 4-chars-per-token estimate the router uses elsewhere.
_REFLECTION_CTX_TOKENS = 1_000


class Reflector:
    """Gera reflexão verbal para corrigir falha."""

    def __init__(self, agent: AgentModel):
        from aios.core.providers import get_provider
        from aios.core.router import route

        # A reflection is a fixed-format two-sentence self-critique with no
        # tools and no external effect. It was inheriting the agent's own
        # model, so a gpt-4o agent paid frontier prices for it on every failed
        # run. Routed instead of hardcoded, so it respects `min_tier` when an
        # operator has asked for a quality floor.
        decision = route(
            agent.llm_config.get("model", "openai/gpt-4o"),
            context_tokens=_REFLECTION_CTX_TOKENS,
            tools=None,
            autonomy="autonomous",
            min_tier=agent.llm_config.get("min_tier") or None,
        )
        self.llm = get_provider(decision.model)
        self.agent = agent
        self.model = decision.model

    async def reflect(self, evaluation: Dict, trajectory: List[dict], user_message: str) -> str:
        """Chama LLM para gerar reflexão 2-shot."""
        prompt = f"""Você é um crítico que reflete sobre falha de agente.

Tarefa: {user_message}
Trajetória: {json.dumps(trajectory[-4:], ensure_ascii=False)[:3000]}
Falha: {evaluation['reason']}

Gere reflexão em 2 frases: 1) o que errou, 2) o que fazer diferente. Seja específico e acionável.
Exemplo: "Errei ao prometer preço sem calcular ROI. Próxima: chamar calculator (8000 vs 249) antes de responder."
Reflexão:"""
        try:
            resp = await self.llm.chat_retry(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.7,
                max_tokens=300,
            )
            reflection = resp.get("content", "").strip()
            if len(reflection) < 20:
                reflection = f"Falha: {evaluation['reason']}. Próxima: verificar tools antes de responder."
            return reflection
        except Exception as e:
            logger.warning("Reflection failed: %s", e)
            return f"Falha: {evaluation['reason']}. Tentar abordagem diferente."


class AutonomousAgent:
    """Wrapper 100% autônomo com HITL."""

    def __init__(self, agent: AgentModel, db_session_factory=None):
        self.agent = agent
        self.runtime = AgentRuntime(agent, db_session_factory)
        self.evaluator = Evaluator()
        self.reflector = Reflector(agent)
        self.max_trials = agent.governance_config.get("max_trials", MAX_TRIALS) if agent.governance_config else MAX_TRIALS
        # HITL config — só quando realmente não pode resolver ou exige aprovação humana
        gov = agent.governance_config or {}
        self.hitl_enabled = gov.get("hitl_enabled", True)
        self.hitl_value_threshold = gov.get("hitl_value_threshold", HITL_VALUE_THRESHOLD)
        self.hitl_discount_threshold = gov.get("hitl_discount_threshold", 10)  # % desconto que exige aprovação

    async def run(
        self,
        conversation_id: str,
        user_message: str,
        db=None,
        emit=None,
    ) -> str:
        """Loop autônomo até done verificado ou HITL.

        ``emit`` is an optional async callback receiving each event as it
        happens. It exists so the agent canvas can show trial boundaries and
        live tokens; the default keeps the historical drain-only behaviour.
        """
        reflections: List[str] = []
        trajectory: List[dict] = []
        last_response = ""
        last_tool_calls = None

        for trial in range(1, self.max_trials + 1):
            # Injeta reflexões anteriores no contexto
            augmented_message = user_message
            if reflections:
                augmented_message = f"[Reflexões anteriores: {' | '.join(reflections[-2:])}]\n\n{user_message}"

            # Executa via AgentRuntime
            try:
                # Reflections reach the model through `augmented_message` above.
                # They used to be appended to `self.agent.system_prompt` instead
                # and restored afterwards — but `self.agent` is the ORM row the
                # caller's session owns, and AgentRuntime commits that session
                # mid-run, so SQLAlchemy autoflushed the reflection text into
                # agents.system_prompt and the customer's deployed prompt was
                # permanently overwritten. One injected copy, no mutation.
                if emit is not None:
                    await emit(
                        emit_trial_event(
                            self.agent, trial, self.max_trials, conversation_id
                        )
                    )

                # Stream the inner runtime rather than draining it, so tokens
                # reach the canvas as they are produced. AgentRuntime.run() was
                # exactly this drain, so behaviour is otherwise unchanged.
                chunks: List[str] = []
                trial_tool_calls: List[dict] = []
                async for _ev in self.runtime.run_stream(
                    conversation_id, augmented_message, db
                ):
                    if _ev.get("type") == STREAM_TOKEN:
                        chunks.append(_ev.get("content", ""))
                    elif _ev.get("type") == STREAM_TOOL_CALL:
                        # Collected so Evaluator case 4 can actually see a tool
                        # error. It was declared and never assigned, so
                        # `last_tool_calls` was always None and the check was
                        # dead code: a run whose tool returned "Tool error: ..."
                        # was judged a success and the bad answer shipped.
                        trial_tool_calls.extend(_ev.get("tool_calls") or [])
                    if emit is not None:
                        await emit(_ev)
                response = "".join(chunks)
                if trial_tool_calls:
                    last_tool_calls = trial_tool_calls

                # Captura trajectory
                trajectory.append({"trial": trial, "response": response[:500], "success": False, "reason": ""})
                # Salva trace no conversation para timeline
                if db and conversation_id:
                    try:
                        from aios.db.backend import db_session as _db_sess
                        from aios.db.models import Conversation as _Conv
                        async with _db_sess() as _db:
                            _conv = await _db.get(_Conv, conversation_id)
                            if _conv:
                                _extra = dict(_conv.extra_data or {})
                                _trace = list(_extra.get("autonomous_trace", []))
                                _trace.append({"trial": trial, "response": response[:300], "success": False, "reason": "pending", "reflection": reflections[-1] if reflections else ""})
                                _extra["autonomous_trace"] = _trace[-5:]
                                _conv.extra_data = _extra
                                await _db.commit()
                    except Exception:
                        pass

                # HITL check: valor > threshold
                if self.hitl_enabled and self._needs_hitl(response, user_message):
                    hitl_id = await self._create_hitl(conversation_id, user_message, response, db)
                    return f"⏸️ [HITL] Ação requer aprovação humana (ID: {hitl_id}). Valor > R${self.hitl_value_threshold}. Aguardando aprovação."

                # Avalia
                evaluation = self.evaluator.evaluate(trajectory, response, last_tool_calls)
                logger.info("Autonomous trial %d/%d: success=%s reason=%s", trial, self.max_trials, evaluation["success"], evaluation["reason"])
                # Atualiza último trial com resultado da avaliação
                if trajectory:
                    trajectory[-1]["success"] = evaluation["success"]
                    trajectory[-1]["reason"] = evaluation["reason"]
                    trajectory[-1]["confidence"] = evaluation.get("confidence", 0)
                    # Atualiza trace no DB
                    if db and conversation_id:
                        try:
                            from aios.db.backend import db_session as _db_sess2
                            from aios.db.models import Conversation as _Conv2
                            async with _db_sess2() as _db2:
                                _conv2 = await _db2.get(_Conv2, conversation_id)
                                if _conv2:
                                    _extra2 = dict(_conv2.extra_data or {})
                                    _trace2 = list(_extra2.get("autonomous_trace", []))
                                    if _trace2:
                                        _trace2[-1].update({"success": evaluation["success"], "reason": evaluation["reason"], "confidence": evaluation.get("confidence", 0)})
                                        _extra2["autonomous_trace"] = _trace2[-5:]
                                        _conv2.extra_data = _extra2
                                        await _db2.commit()
                        except Exception:
                            pass

                if evaluation["success"]:
                    # Extrai skill se sucesso após retry (aprendizado)
                    if trial > 1 and reflections:
                        await self._extract_skill(user_message, trajectory, reflections, db)
                    # Consolidation: hot buffer -> long term (simplificado)
                    await self._consolidate_memory(conversation_id, reflections, db)
                    return response

                # Falha: gera reflexão e tenta de novo
                reflection = await self.reflector.reflect(evaluation, trajectory, user_message)
                reflections.append(reflection)
                logger.info("Reflection %d: %s", trial, reflection[:200])
                last_response = response

                # Pequeno delay para não spammar
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.exception("Autonomous trial %d failed", trial)
                reflections.append(f"Erro técnico: {e}. Tentar abordagem diferente.")
                last_response = f"Erro: {e}"

        # Após max_trials, verifica confiança para HITL
        if self.hitl_enabled:
            # Se ainda falhou, pede humano
            hitl_id = await self._create_hitl(conversation_id, user_message, last_response, db, reason="Falha após 3 tentativas autônomas")
            return f"⏸️ [HITL] Não consegui resolver autonomamente após {self.max_trials} tentativas. Reflexões: {' | '.join(reflections[-2:])}. Aguardando humano (ID: {hitl_id}). Última tentativa: {last_response[:500]}"

        return last_response or "Não consegui resolver. Tente reformular."

    async def run_stream(
        self, conversation_id: str, user_message: str, db=None
    ):
        """Stream an autonomous run, including trial boundaries.

        The trial loop in :meth:`run` is a coroutine, so it cannot itself be
        iterated. Fan-in via a queue: ``run`` pushes events into the queue as
        it produces them, and this generator yields whatever arrives until the
        run finishes.

        Note each trial calls the inner runtime, which fires AGENT_START and
        AGENT_END per attempt. Subscribers must treat node lifecycle as an
        idempotent state set, not a counter.
        """
        import asyncio as _asyncio

        q: "_asyncio.Queue[dict]" = _asyncio.Queue()

        async def _emit(ev: dict) -> None:
            await q.put(ev)

        task = _asyncio.create_task(
            self.run(conversation_id, user_message, db, emit=_emit)
        )
        try:
            while True:
                getter = _asyncio.create_task(q.get())
                done, _ = await _asyncio.wait(
                    {getter, task}, return_when=_asyncio.FIRST_COMPLETED
                )
                if getter in done:
                    yield getter.result()
                else:
                    getter.cancel()
                    break
            # Drain anything queued between the run finishing and this check.
            while not q.empty():
                yield q.get_nowait()
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except (_asyncio.CancelledError, Exception):
                pass

    def _needs_hitl(self, response: str, user_message: str) -> bool:
        """Heurística HITL: só quando realmente não pode resolver ou exige aprovação humana.
        - Valor alto (≥R$5k + deal) → precisa aprovação
        - Desconto >X% → precisa aprovação (ex: 10%)
        - Delete/drop → precisa aprovação
        - Fora disso, autônomo resolve sozinho
        """
        text = (response + " " + user_message).lower()
        import re
        # 1. Valor alto (≥R$5k + deal/proposta) → HITL
        for m in re.finditer(r"r\$\s*([\d.,]+)\s*(k)?|(\d+)\s*reais|\b(\d+)k\b", text):
            val_str = m.group(1) or m.group(3) or m.group(4)
            if not val_str:
                continue
            try:
                is_k = bool(m.group(2) or m.group(4))
                val_clean = val_str.replace(".", "").replace(",", ".")
                if "." in val_str and "," not in val_str and len(val_str.split(".")[-1]) == 3:
                    val_clean = val_str.replace(".", "")
                val = float(val_clean)
                if is_k:
                    val *= 1000
                if val >= self.hitl_value_threshold:
                    if "crm_update" in text or "deal" in text or "proposta" in text:
                        return True
            except Exception:
                continue
        if re.search(r"\b[5-9]\s*k\b|\b\d{2,}\s*k\b", text):
            if "crm_update" in text or "deal" in text or "proposta" in text:
                return True
        # 2. Desconto >X% → HITL (ex: 15% desconto)
        for m in re.finditer(r"(\d+)\s*%\s*(desconto|off|discount)", text):
            try:
                pct = int(m.group(1))
                if pct >= self.hitl_discount_threshold:
                    return True
            except Exception:
                continue
        if "desconto" in text and any(f"{p}%" in text for p in range(self.hitl_discount_threshold, 100)):
            return True
        # 3. Delete / drop → HITL
        #
        # Only when the user ASKS for the destructive action. The old check
        # scanned `response + user_message`, so ordinary phrasing ("remove the
        # duplicate lead", "apaga o contato antigo") matched and the agent
        # replied "⏸️ [HITL]" instead of doing the job, on the first try, every
        # time. Scan the user's own request and require the verb, not the nouns
        # that sit next to it.
        if re.search(
            r"\b(?:delet\w+|dro\w+|apag\w+|remov\w+|exclu\w+|elimin\w+)\b",
            (user_message or "").lower(),
        ):
            return True
        return False

    async def _create_hitl(self, conversation_id: str, user_message: str, response: str, db, reason: str = "Valor > threshold") -> str:
        """Cria PendingAction para humano aprovar."""
        try:
            import uuid
            action_id = str(uuid.uuid4())
            # request_approval BLOCKS until a human decides (or the 300s timeout
            # expires). It was awaited here on the hot path of every HITL reply,
            # so creating the approval parked the agent run for five minutes,
            # and its return value — the actual verdict — was discarded. Return
            # the id immediately and let the row be decided out of band.
            import asyncio as _aio

            _aio.create_task(self._await_hitl_decision(
                action_id, conversation_id, user_message, response, reason
            ))
            return action_id
        except Exception as e:
            logger.warning("HITL creation failed: %s", e)
            return "falha ao criar aprovação"

    async def _await_hitl_decision(
        self, action_id: str, conversation_id: str,
        user_message: str, response: str, reason: str,
    ) -> None:
        """Persist the HITL row and wait for the verdict. Never raises."""
        try:
            from aios.core.approval import approval_manager

            ok = await approval_manager.request_approval(
                action_id=action_id,
                agent_id=self.agent.id,
                org_id=self.agent.org_id,
                conversation_id=conversation_id,
                tool_name="autonomous_hitl",
                tool_args={
                    "user_message": user_message,
                    "response": response[:500],
                    "reason": reason,
                },
                context_summary=f"HITL: {reason}",
            )
            logger.info("HITL %s decided: approved=%s", action_id, ok)
        except Exception:
            logger.exception("HITL %s could not be recorded", action_id)

    async def _extract_skill(self, user_message: str, trajectory: List[dict], reflections: List[str], db):
        """Extrai skill de trajetória de sucesso (ELL)."""
        try:
            from aios.core.skills import skill_store
            # Só extrai se teve reflexão e sucesso no retry
            if len(reflections) < 1:
                return
            skill_name = f"auto:{user_message[:30].lower().replace(' ', '_')}"
            skill_content = f"Task: {user_message}\nReflections: {' | '.join(reflections)}\nSuccess trajectory: {json.dumps(trajectory[-2:], ensure_ascii=False)[:1000]}"
            await skill_store.create(
                agent_id=self.agent.id,
                org_id=self.agent.org_id,
                name=skill_name,
                description=f"Auto-extraída de sucesso após {len(reflections)} reflexões",
                skill_type="auto_learned",
                content=skill_content,
                source_conversation_id=trajectory[0].get("conversation_id") if trajectory else None,
            )
            logger.info("Skill auto-extraída: %s", skill_name)
        except Exception as e:
            logger.debug("Skill extraction failed: %s", e)

    async def _consolidate_memory(self, conversation_id: str, reflections: List[str], db):
        """Consolidação dual-buffer (U-Mem style): hot -> long_term após validação."""
        if not reflections:
            return
        try:
            # Injeta reflexão no memory como episodic
            await self.runtime.memory.add(conversation_id, "system", f"[Reflexão aprendida] {' | '.join(reflections[-2:])}")
        except Exception:
            pass
