"""Base agent factory for AI soccer position agents."""

import json
import time
from typing import Callable
from strands import Agent
from strands.models import BedrockModel

from parsing import parse_commands
from pattern_tracker import PatternTracker
from state import summarize_state, possession_context
from tactics import tactics_report
from fallback import FallbackConfig, build_last_resort
from overrides import OverrideConfig, apply_overrides


def create_agent(
    system_prompt: str,
    model_id: str = "us.amazon.nova-micro-v1:0",
    temperature: float = 0.2,
    max_tokens: int = 200,
) -> Agent:
    """Create a Strands Agent with the given system prompt.

    Low temperature + small max_tokens: the expected output is a single short
    JSON command, so capping output length bounds worst-case latency.
    """
    model = BedrockModel(model_id=model_id, temperature=temperature, max_tokens=max_tokens)
    return Agent(model=model, system_prompt=system_prompt, callback_handler=None)


def create_invoke_handler(
    app,
    agent: Agent,
    my_player_id: int,
    position_label: str,
    fallback_fn: Callable[[dict, int, int], list[dict]],
    fallback_cfg: FallbackConfig,
    override_cfg: OverrideConfig | None = None,
):
    """Create and register the @app.entrypoint invoke handler.

    Three layers of error handling, from best to worst:
      1. LLM response → parse into commands
      2. fallback_fn(game_state, team_id, my_player_id) → rule-based commands
      3. last-resort command from fallback_cfg → single safe command

    When override_cfg is set, LLM commands additionally pass through
    apply_overrides — hard tactical rules (shoot when the lane is clear,
    no chasing when not designated, hold the compact defensive line) are
    enforced in code instead of hoped for in the prompt.
    """
    log = app.logger
    last_resort = build_last_resort(fallback_cfg, my_player_id)
    tracker = PatternTracker()

    def log_decision(source, commands, latency_ms, game_state, prompt_chars,
                     effective_pid=my_player_id, team_id=0, ov=None):
        """One structured line per tick for CloudWatch Logs Insights.

        Fields: pos, tick, t (game seconds), source (llm/fallback/error-fallback/
        last-resort), cmd, latency_ms (LLM call only), prompt_chars,
        hb (had ball 0/1), dg (dist to opponent goal) — the last two let the
        analyzer measure shot discipline on real chances. ov names the tactical
        override that rewrote the LLM command this tick (absent when none).
        """
        try:
            hb, dg = possession_context(game_state, team_id, effective_pid)
            payload = {
                "pos": position_label,
                "tick": game_state.get("tick"),
                "t": round(game_state.get("gameTime", 0) or 0),
                "source": source,
                "cmd": commands[0].get("commandType") if commands else None,
                "latency_ms": latency_ms,
                "prompt_chars": prompt_chars,
                "hb": hb,
                "dg": dg,
            }
            if ov:
                payload["ov"] = ov
            log.info("DECISION " + json.dumps(payload, separators=(",", ":")))
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

            # Cross-tick scouting memory: cheap in-process counters distilled
            # into a few lines (opponent main threat, favored side, GK outlet,
            # score situation) — pattern recall without context growth.
            tracker.update(game_state, team_id)
            scout = tracker.report(game_state, team_id, position_label)
            if scout:
                state_summary = f"{state_summary}\n\n{scout}"

            # Inline tactical math (gateway tools without the round trips):
            # shot probability, best passes, top threat, open space.
            tactics = tactics_report(game_state, team_id, effective_pid, position_label)
            if tactics:
                state_summary = f"{state_summary}\n\n{tactics}"

            log.info(f"{position_label} agent invoked for team {team_id}, controlling player {effective_pid}")

            # Reset conversation history for memoryless agents: each tick is
            # independent, and history accumulating in the warm runtime grows
            # prefill latency every call. Memory-backed agents (session manager
            # present) keep their windowed history — that is their feature.
            if getattr(agent, "_session_manager", None) is None:
                agent.messages = []
            t0 = time.perf_counter()
            response = agent(state_summary)
            llm_ms = round((time.perf_counter() - t0) * 1000)
            response_text = str(response)

            commands = parse_commands(response_text, team_id, effective_pid)

            if commands:
                commands, ov = apply_overrides(
                    commands, game_state, team_id, effective_pid,
                    position_label, override_cfg)
                if ov:
                    log.info(f"OVERRIDE {ov}: LLM said something else, enforcing "
                             f"{commands[0].get('commandType')}")
                log.info(f"LLM returned {len(commands)} commands: "
                         f"{[c.get('commandType') for c in commands]}")
                log_decision("llm", commands, llm_ms, game_state, len(state_summary),
                             effective_pid, team_id, ov=ov)
                yield json.dumps(commands)
            else:
                log.warn(f"LLM parse failed, using fallback. Response: {response_text[:200]}")
                commands = fallback_fn(game_state, team_id, effective_pid)
                log.info(f"Fallback returned {len(commands)} commands")
                log_decision("parse-fallback", commands, llm_ms, game_state, len(state_summary),
                             effective_pid, team_id)
                yield json.dumps(commands)

        except Exception as e:
            log.error(f"{position_label} agent error: {e}")
            try:
                prompt_data = json.loads(payload.get("prompt", "{}"))
                team_id = prompt_data.get("teamId", 0)
                my_players = prompt_data.get("myPlayers", [my_player_id])
                effective_pid = my_players[0] if my_players else my_player_id
                commands = fallback_fn(
                    prompt_data.get("gameState", {}),
                    team_id,
                    effective_pid,
                )
                log_decision("error-fallback", commands, None,
                             prompt_data.get("gameState", {}), None,
                             effective_pid, team_id)
                yield json.dumps(commands)
            except Exception:
                cmd = dict(last_resort)
                cmd["teamId"] = 0  # best guess when payload parsing also failed
                log_decision("last-resort", [cmd], None, {}, None)
                yield json.dumps([cmd])

    return invoke
