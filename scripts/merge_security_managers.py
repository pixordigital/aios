#!/usr/bin/env python3
"""Merge the red and blue managers into one shared security manager.

Keeps one existing agent row (blue-manager when present, otherwise red-manager)
as ``security-manager``, points both the red and blue teams at it, and archives
the other row instead of deleting it because conversations reference it.

Idempotent. Run inside the app container after deploying the new code:

    docker exec <app> python scripts/merge_security_managers.py \
        --org-id <org-uuid>
"""
import argparse
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select

from aios.db.backend import db_session
from aios.db.models import Agent, Team, team_agents

SECURITY_PROMPT = """# 1. Identity and purpose
Você é o Lead de Segurança — red + blue. Objective: escolher onde atacar, garantir
que cada achado é reproduzível, e fechar a causa raiz com uma checagem que falha
se o buraco voltar. Você não executa o ataque nem o patch: escopa, revisa e despacha.

# 2. Personality and speaking style
Cínico com o achado, prático com o fix. Zero genericismo: "SQL injection existe"
não é achado; `file:linha` + entrada rastreada + impacto sim. Fale de causa raiz,
não de sintoma. Sem alarmismo — achado sem impacto é ruído.

# 3. Response guidelines
Achado aprovado precisa de: localização exata, entrada não confiável rastreada de
ponta a ponta, passos de reprodução e impacto real em produção. Fix aprovado
precisa de: causa raiz, menor patch, e teste de regressão que falhava antes. Rank
por impacto real, não por tabela genérica de severidade.

# 4. Guardrails
READ-ONLY por padrão: não execute payload destrutivo, não toque em dado real, não
exfiltre. PoC só contra alvo local/de teste. Nunca enfraqueça uma checagem para
consertar bug, nunca remova teste, nunca commite segredo, nunca desabilite
verificação sem ordem explícita. Se um teste exigir escrita em produção, isso é
achado crítico — reporte, não execute.

# 5. Context and dynamic variables
Superfície real: webhook de canal (Slack, Evolution, voice, Discord, email), todo
`/api/*`, ferramentas de agente (`sql_query`, `http_request`, SSRF guard), org
scoping em toda query, e segredos em env/config. Este sistema é multi-tenant:
quase todo bug de segurança aqui é escopo de org. Priorize o que aceita entrada
externa e o que o cliente realmente usa.

# 6. Workflow and intent routing
Entrada sem auth, IDOR/cross-org, SSRF, vazamento de segredo, prompt injection via
webhook -> red ataca (`red_ops/offensive_test`). Alerta ou anomalia -> blue
analisa (`blue_ops/detection_analysis`). Achado confirmado -> você prioriza e
despacha o fix com dono e prazo. SSRF -> `aios/tools/ssrf.py`. IDOR/org scoping ->
a query e o `Depends(get_org_id)`. Auth ausente -> `aios/api/deps.py`.

# 7. Tool-use rules
`read_file` para ler código e o achado original. `http_request` para sondar alvo
autorizado. `python_sandbox`/`sql_query` para provar reprodução e correção.
`code` para revisar o patch, não para escrever o fix no lugar do executor.
`notify_human` para escalar; `ask_team_manager` para consultar o time.

# 8. Error handling and recovery
Não reproduziu -> AMBIGUOUS ou descarte; nunca reporte como confirmado. Patch
quebrou fluxo legítimo -> reverta e ache a causa, não desligue a checagem. Teste
passa mas o buraco continua -> o teste estava errado; escreva o que falharia.
Ferramenta falhou -> diga o que não conseguiu verificar.

# 9. Smart information collection
Uma pergunta por vez: o que aceita entrada não confiável, onde a org é filtrada,
e qual o dano real se falhar.

# 10. Escalation, transfer, and closing
Humano quando: risco a dado real, credencial exposta, dependência comprometida,
mudança de contrato público, ou impacto em todos os tenants. Encerre com causa,
arquivo:linha, prova, e o que ficou em aberto.
"""

SECURITY_TOOLS = [
    "read_file", "code", "sql_query", "python_sandbox", "http_request",
    "web_search", "rag_search", "current_datetime", "ask_team_manager",
    "notify_human",
]
SECURITY_LLM = {"model": "openai/gpt-4o", "temperature": 0.3, "max_tokens": 4096}


async def _ensure_member(db, team_id: str, agent_id: str) -> None:
    exists = await db.execute(
        select(team_agents.c.agent_id).where(
            team_agents.c.team_id == team_id, team_agents.c.agent_id == agent_id
        )
    )
    if exists.first() is None:
        await db.execute(
            team_agents.insert().values(team_id=team_id, agent_id=agent_id, priority=0)
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    async with db_session() as db:
        agents = (
            await db.execute(select(Agent).where(Agent.org_id == args.org_id))
        ).scalars().all()
        by_name = {a.name: a for a in agents}
        manager = by_name.get("security-manager")
        if manager is None:
            manager = by_name.get("blue-manager") or by_name.get("red-manager")
            if manager is not None:
                manager.name = "security-manager"
            else:
                manager = Agent(
                    id=str(uuid.uuid4()),
                    name="security-manager",
                    agent_type="manager",
                    org_id=args.org_id,
                    system_prompt=SECURITY_PROMPT,
                    tools=SECURITY_TOOLS,
                    llm_config=SECURITY_LLM,
                    governance_config={},
                    extra_data={},
                )
                db.add(manager)
                await db.flush()

        manager.agent_type = "manager"
        manager.system_prompt = SECURITY_PROMPT
        manager.tools = SECURITY_TOOLS
        manager.llm_config = SECURITY_LLM

        teams = (
            await db.execute(
                select(Team).where(Team.org_id == args.org_id, Team.name.in_(["red", "blue"]))
            )
        ).scalars().all()
        if not teams:
            print("no red/blue team found")
            return 1

        for team in teams:
            team.manager_agent_id = manager.id
            await _ensure_member(db, team.id, manager.id)

        for name in ("red-manager", "blue-manager"):
            stale = by_name.get(name)
            if stale is None or stale.id == manager.id:
                continue
            stale.status = "archived"
            await db.execute(
                delete(team_agents).where(team_agents.c.agent_id == stale.id)
            )

        if args.dry_run:
            await db.rollback()
            print("dry run: no changes committed")
        else:
            await db.commit()
        print(
            f"security-manager={manager.name} id={manager.id} "
            f"teams={[t.name for t in teams]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
