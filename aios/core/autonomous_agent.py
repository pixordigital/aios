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
        # HITL config
        gov = agent.governance_config or {}
        self.hitl_enabled = gov.get("hitl_enabled", True)
        self.hitl_value_threshold = gov.get("hitl_value_threshold", HITL_VALUE_THRESHOLD)

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

                # Captura trajectory (simplificado: resposta + tools)
                # For now, we use the runtime's last context; in full impl, hook into scheduler
                trajectory.append({"trial": trial, "response": response[:500]})

                # HITL check: valor > threshold
                if self.hitl_enabled and self._needs_hitl(response, user_message):
                    hitl_id = await self._create_hitl(conversation_id, user_message, response, db)
                    return f"⏸️ [HITL] Ação requer aprovação humana (ID: {hitl_id}). Valor > R${self.hitl_value_threshold}. Aguardando aprovação."

                # Avalia
                evaluation = self.evaluator.evaluate(trajectory, response, last_tool_calls)
                logger.info("Autonomous trial %d/%d: success=%s reason=%s", trial, self.max_trials, evaluation["success"], evaluation["reason"])

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
        """Heurística HITL: valor alto, delete, ou fora da janela."""
        text = (response + " " + user_message).lower()
        # Valor
        import re
        # Busca R$ 5.000, R$5000, 5000 reais
        if re.search(r"r\$\s*5\.?0{3,}|5000|\b5k\b", text):
            # Se menciona valor e vai fazer crm_update_deal, precisa HITL
            if "crm_update" in text or "deal" in text or "proposta" in text:
                return True
        # Delete / drop
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
