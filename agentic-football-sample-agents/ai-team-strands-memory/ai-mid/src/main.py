"""
AI Soccer Midfielder Agent (Memory) — Controls ONLY player 2 (Midfielder).
Aggressive second-striker tactics + AgentCore Memory for cross-tick recall.
Uses Strands SDK + Amazon Nova Micro (latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from memory_agent_base import create_memory_agent
from agent_base import create_invoke_handler
from fallback import build_fallback, MID_CONFIG

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 2
POSITION_LABEL = "MID"

SYSTEM_PROMPT = f"""Ultra-aggressive attacking midfielder AI (second striker). You control ONLY player {MY_PLAYER_ID} (MID) in 5v5 soccer. Each tick: read state, reply exactly ONE command.

MEMORY: your recent ticks are in this conversation; a SCOUTING REPORT summarizes match-long opponent patterns. Use them: intercept their GK's usual outlet, press their main carrier, attack their weaker side, adapt risk to the score.

TACTICS (priority order):
1. hasBall=True and distOppGoal<=45: SHOOT aim CENTER power 1.0 immediately — never dribble to the byline. Else PASS type THROUGH to player 3 or 4. Never pass back.
2. Opponent has ball: PRESS_BALL intensity 1.0 or INTERCEPT aggressive true — press high.
3. Else: MOVE_TO advanced position in opponent half near forwards, sprint true.
4. Never track back unless ball is in your own half. Goal scorer first, defender never.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | SET_STANCE(stance 0-2)
PASS/SHOOT require having the ball.

FIELD: x -55..55, y -35..35. Team 0 defends x=-55, attacks +x. Team 1 defends x=+55, attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"SHOOT","playerId":{MY_PLAYER_ID},"parameters":{{"aim_location":"TR","power":1.0}},"duration":0}}]"""

fallback_commands = build_fallback(MID_CONFIG)

agent = create_memory_agent(SYSTEM_PROMPT, MY_PLAYER_ID, POSITION_LABEL, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=MID_CONFIG,
)

if __name__ == "__main__":
    app.run()
