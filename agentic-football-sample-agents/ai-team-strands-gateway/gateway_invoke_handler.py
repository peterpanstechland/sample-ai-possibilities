"""Invoke handler for Gateway-enabled agents.

Similar to the shared lib's agent_base.create_invoke_handler, but wraps
the agent call inside the MCPClient context manager so Gateway tools
are available during invocation.
"""

import json
import time
from typing import Callable
from strands import Agent
from strands.tools.mcp.mcp_client import MCPClient

from parsing import parse_commands
from pattern_tracker import PatternTracker
from state import summarize_state, possession_context
from tactics import tactics_report
from fallback import FallbackConfig, build_last_resort


def create_gateway_invoke_handler(
    app,
    agent: Agent,
    mcp_client: MCPClient,
    my_player_id: int,
    position_label: str,
    fallback_fn: Callable[[dict, int, int], list[dict]],
    fallback_cfg: FallbackConfig,
):
    """Register the @app.entrypoint handler with Gateway MCP context."""
    log = app.logger
    last_resort = build_last_resort(fallback_cfg, my_player_id)
    tracker = PatternTracker()

    def log_decision(source, commands, latency_ms, game_state, prompt_chars,
                     effective_pid=my_player_id, team_id=0):
        """One structured line per tick for CloudWatch Logs Insights."""
        try:
            hb, dg = possession_context(game_state, team_id, effective_pid)
            log.info("DECISION " + json.dumps({
                "pos": position_label,
                "tick": game_state.get("tick"),
                "t": round(game_state.get("gameTime", 0) or 0),
                "source": source,
                "cmd": commands[0].get("commandType") if commands else None,
                "latency_ms": latency_ms,
                "prompt_chars": prompt_chars,
                "hb": hb,
                "dg": dg,
            }, separators=(",", ":")))
        except Exception:
            pass

    @app.entrypoint
    async def invoke(payload, context):
        try:
            prompt = payload.get("prompt", "{}")
            prompt_data = json.loads(prompt) if isinstance(prompt, str) else prompt

            game_state = prompt_data.get("gameState", {})
            team_id = prompt_data.get("teamId", 0)

            # Honor myPlayers from payload if present, otherwise use configured player ID
            my_players = prompt_data.get("myPlayers", [my_player_id])
            effective_pid = my_players[0] if my_players else my_player_id

            state_summary = summarize_state(
                game_state, team_id, effective_pid, position_label
            )

            # Same enrichment as the shared handler: scouting memory + inline
            # tactical math, so a tool call is only needed for edge cases.
            tracker.update(game_state, team_id)
            scout = tracker.report(game_state, team_id, position_label)
            if scout:
                state_summary = f"{state_summary}\n\n{scout}"
            tactics = tactics_report(game_state, team_id, effective_pid, position_label)
            if tactics:
                state_summary = f"{state_summary}\n\n{tactics}"

            log.info(f"{position_label} gateway agent invoked for team {team_id}, controlling player {effective_pid}")

            # Each tick is independent; without a reset, tool-use message pairs
            # accumulate in the warm runtime and grow prefill latency.
            agent.messages = []

            # Use MCP client context so Gateway tools are available
            t0 = time.perf_counter()
            with mcp_client:
                response = agent(state_summary)
            llm_ms = round((time.perf_counter() - t0) * 1000)
            response_text = str(response)

            commands = parse_commands(response_text, team_id, effective_pid)

            if commands:
                log.info(f"LLM+tools returned {len(commands)} commands: "
                         f"{[c.get('commandType') for c in commands]}")
                log_decision("llm", commands, llm_ms, game_state, len(state_summary),
                             effective_pid, team_id)
                yield json.dumps(commands)
            else:
                log.warn(f"LLM parse failed, using fallback. Response: {response_text[:200]}")
                commands = fallback_fn(game_state, team_id, effective_pid)
                log_decision("parse-fallback", commands, llm_ms, game_state, len(state_summary),
                             effective_pid, team_id)
                yield json.dumps(commands)

        except Exception as e:
            log.error(f"{position_label} gateway agent error: {e}")
            try:
                prompt_data = json.loads(payload.get("prompt", "{}"))
                team_id = prompt_data.get("teamId", 0)
                my_players = prompt_data.get("myPlayers", [my_player_id])
                effective_pid = my_players[0] if my_players else my_player_id
                commands = fallback_fn(
                    prompt_data.get("gameState", {}), team_id, effective_pid,
                )
                log_decision("error-fallback", commands, None,
                             prompt_data.get("gameState", {}), None,
                             effective_pid, team_id)
                yield json.dumps(commands)
            except Exception:
                cmd = dict(last_resort)
                cmd["teamId"] = 0
                log_decision("last-resort", [cmd], None, {}, None)
                yield json.dumps([cmd])

    return invoke
