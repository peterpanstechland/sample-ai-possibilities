"""Memory-aware agent factory for AI soccer position agents.

Extends the shared lib's agent_base with AgentCoreMemorySessionManager so each
agent persists conversation history across game ticks.

Latency-tuned:
  - SlidingWindowConversationManager caps in-context history to the last few
    ticks (raw replay of a whole match buries the signal and grows prefill
    latency every tick). Match-long patterns come from lib/pattern_tracker.py
    (SCOUTING REPORT), not from raw history.
  - batch_size=2 groups each tick's user+assistant pair into one Memory write
    instead of two synchronous calls.
  - Same inference caps as the fast teams (temperature 0.2, max_tokens 200).
"""

import os
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models import BedrockModel
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig


def create_memory_agent(
    system_prompt: str,
    player_id: int,
    position_label: str,
    model_id: str = "us.amazon.nova-micro-v1:0",
    temperature: float = 0.2,
    max_tokens: int = 200,
    window_ticks: int = 5,
) -> Agent:
    """Create a Strands Agent backed by AgentCore Memory (STM).

    Required env vars:
      MEMORY_ID  — AgentCore Memory resource ID
      TEAM_ID    — used as actor_id and session_id prefix
    Optional:
      MATCH_TAG  — appended to session_id to isolate matches (prevents one
                   match's history polluting the next; without it the fixed
                   session grows forever across matches)
    """
    memory_id = os.environ.get("MEMORY_ID")
    team_id = os.environ.get("TEAM_ID", "default-team")
    match_tag = os.environ.get("MATCH_TAG", "")

    if not memory_id:
        raise RuntimeError("MEMORY_ID environment variable is required")

    session_id = f"match-{team_id}-{position_label}"
    if match_tag:
        session_id = f"{session_id}-{match_tag}"

    session_manager = AgentCoreMemorySessionManager(
        agentcore_memory_config=AgentCoreMemoryConfig(
            memory_id=memory_id,
            session_id=session_id,
            actor_id=f"{team_id}-{position_label}",
            batch_size=2,
        ),
        region_name=os.environ.get("AWS_DEFAULT_REGION"),
    )

    model = BedrockModel(model_id=model_id, temperature=temperature, max_tokens=max_tokens)
    return Agent(
        model=model,
        system_prompt=system_prompt,
        session_manager=session_manager,
        # window_size counts messages; each tick adds a user+assistant pair
        conversation_manager=SlidingWindowConversationManager(window_size=window_ticks * 2),
        callback_handler=None,
    )
