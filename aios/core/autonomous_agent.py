"""Autonomous Agent — 100% autônomo com HITL se necessário.

Implementa ReAct + Reflexion (Shinn et al. 2023) + U-Mem dual-buffer.
Loop: Thought → Action (tool) → Observation → Evaluator → Reflection → Retry (max 3 trials)
Custo zero (verbal, sem fine-tuning). HITL apenas quando necessário.

Referências: Reflexion, ReAct, ReflAct, ELL, U-Mem, Agentic Memory
"""

import asyncio
import json
import logging
import time
from typing import Dict, List

from aios.core.agent import AgentRuntime
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


class Reflector:
    """Gera reflexão verbal para corrigir falha."""

    def __init__(self, agent: AgentModel):
        from aios.core.providers import get_provider
        model = agent.llm_config.get("model", "openai/gpt-4o-mini")
        self.llm = get_provider(model)
        self.agent = agent

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
                model=self.agent.llm_config.get("model", "openai/gpt-4o-mini"),
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

    async def run(self, conversation_id: str, user_message: str, db=None) -> str:
        """Loop autônomo até done verificado ou HITL."""
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
                # Build context with reflection injection
                # We do this by temporarily patching the agent's system_prompt
                original_prompt = self.agent.system_prompt
                if reflections:
                    self.agent.system_prompt = original_prompt + "\n\n[Aprendizado de tentativas anteriores]\n" + "\n".join(f"- {r}" for r in reflections[-2:])

                response = await self.runtime.run(conversation_id, augmented_message, db)

                # Restore
                self.agent.system_prompt = original_prompt

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
        if any(kw in text for kw in ["delete", "drop", "deletar", "apagar", "remover"]):
            return True
        return False

    async def _create_hitl(self, conversation_id: str, user_message: str, response: str, db, reason: str = "Valor > threshold") -> str:
        """Cria PendingAction para humano aprovar."""
        try:
            from aios.core.approval import approval_manager
            import uuid
            action_id = str(uuid.uuid4())
            # Tenta criar via approval_manager
            await approval_manager.request_approval(
                action_id=action_id,
                agent_id=self.agent.id,
                conversation_id=conversation_id,
                tool_name="autonomous_hitl",
                tool_args={"user_message": user_message, "response": response[:500], "reason": reason},
                context_summary=f"HITL: {reason}",
            )
            return action_id
        except Exception as e:
            logger.warning("HITL creation failed: %s", e)
            return "pending"

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
