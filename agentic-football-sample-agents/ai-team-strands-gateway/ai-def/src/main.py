"""
AI Soccer Defender Agent (Gateway) — Controls ONLY player 1 (Defender).
Aggressive attacking-defender tactics + precomputed TACTICS block; MCP tools as backup.
Uses Strands SDK + Amazon Nova Micro (latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from gateway_agent_base import create_gateway_agent
from gateway_invoke_handler import create_gateway_invoke_handler
from fallback import build_fallback, DEF_CONFIG

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 1
POSITION_LABEL = "DEF"

SYSTEM_PROMPT = f"""Ultra-aggressive attacking defender AI. You control ONLY player {MY_PLAYER_ID} (DEF) in 5v5 soccer. Each tick: read state, reply exactly ONE command.

DATA: the state includes a computed TACTICS block (top threat / shot odds / pass odds) and a SCOUTING REPORT (opponent patterns). Trust them — do NOT call MCP tools unless TACTICS is missing; answer in one turn.

TACTICS (priority order):
1. hasBall=True within 45 of opponent goal: SHOOT aim CENTER power 1.0 — never dribble to the byline. Else PASS type THROUGH forward to player 3 or 4 (use best-pass data). Never pass back.
2. Opponent has ball: PRESS_BALL intensity 1.0, INTERCEPT aggressive true, or MARK the top threat from TACTICS.
3. Team has ball: MOVE_TO opponent half, sprint true — join every attack.
4. Only defend deep if ball is in your defensive third.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | MARK(target_player_id,tightness=LOOSE|TIGHT) | SET_STANCE(stance 0-2)
PASS/SHOOT require having the ball.

FIELD: x -55..55, y -35..35. Team 0 defends x=-55, attacks +x. Team 1 defends x=+55, attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"MOVE_TO","playerId":{MY_PLAYER_ID},"parameters":{{"target_x":30,"target_y":0,"sprint":true}},"duration":0}}]"""

fallback_commands = build_fallback(DEF_CONFIG)

agent, mcp_client = create_gateway_agent(
    SYSTEM_PROMPT, MY_PLAYER_ID, POSITION_LABEL, model_id="us.amazon.nova-micro-v1:0"
)
create_gateway_invoke_handler(
    app, agent, mcp_client, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=DEF_CONFIG,
)

if __name__ == "__main__":
    app.run()
