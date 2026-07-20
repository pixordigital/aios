"""PIXOR AIOS Python SDK — embed agents into your apps.

Quick start:
    from aios.sdk import AIOSClient

    client = AIOSClient("http://localhost:8777", api_key="...")

    # Deploy an agent
    agent = await client.agents.create("Support Bot", agent_type="support")

    # Send a message
    reply = await agent.send("Refund order #123")
    print(reply)

    # Conversation mode
    conv = await client.conversations.get(conv_id)
    async for msg in conv.stream("Tell me more"):
        print(msg)
"""

from .client import AIOSClient
from .agent import AgentHandle
from .conversation import ConversationHandle

__all__ = ["AIOSClient", "AgentHandle", "ConversationHandle"]
