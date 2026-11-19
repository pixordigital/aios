#!/usr/bin/env python3
"""Utility script to create a default Simple‑Mode agent for a given organization.

Usage:
    python scripts/create_default_simple_agent.py <org-id>

The script uses the `compile_plug_and_play_agent` helper to build a WhatsApp
attendant (the default solution) with the "fast" intelligence level and a few
generic business placeholders. It then inserts the Agent row into the database
and links the first available WhatsApp channel (if any) that does not yet have an
agent.
"""

import sys
import asyncio
from pathlib import Path

# Project imports – we add the repo root to sys.path so the script can be run
# from any location.
repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))

from aios.core.simple_compiler import compile_plug_and_play_agent
from aios.db.models import Agent, ChannelConnection
from aios.core.db import db_session
from sqlalchemy import select


async def create_default_agent(org_id: str) -> None:
    """Create a default Simple‑Mode WhatsApp attendant for *org_id*.

    The function is deliberately simple – it does not attempt to handle edge
    cases like missing migrations or a pre‑existing agent with the same name.
    It is intended for CI, onboarding scripts, or manual use by an operator.
    """
    compiled = compile_plug_and_play_agent(
        solution_key="whatsapp_atendente",
        name="Atendente padrão",
        business_name="Minha Empresa",
        business_description="Produtos e serviços de qualidade",
        intelligence_level="fast",
        tone="amigavel",
        business_hours="Segunda a Sexta, das 08h às 18h",
        off_hours_behavior="take_note",
        rules=[],
        faq_text="",
    )

    async with db_session() as db:
        agent = Agent(
            org_id=org_id,
            name=compiled["name"],
            agent_type=compiled["agent_type"],
            system_prompt=compiled["system_prompt"],
            llm_config=compiled["llm_config"],
            tools=compiled["tools"],
            memory_config=compiled["memory_config"],
            governance_config=compiled["governance_config"],
            extra_data=compiled["extra_data"],
            status="active",
        )
        db.add(agent)
        await db.commit()

        # Bind to first free WhatsApp/Evolution channel, if present.
        wa_ch = (
            await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.org_id == org_id,
                    ChannelConnection.channel_type.in_(["evolution", "whatsapp"]),
                )
            )
        ).scalars().first()
        if wa_ch and not wa_ch.agent_id:
            wa_ch.agent_id = agent.id
            await db.commit()
    print(f"✅ Created Simple‑Mode agent '{agent.name}' (id={agent.id}) for org {org_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/create_default_simple_agent.py <org-id>")
        sys.exit(1)
    org = sys.argv[1]
    asyncio.run(create_default_agent(org))
