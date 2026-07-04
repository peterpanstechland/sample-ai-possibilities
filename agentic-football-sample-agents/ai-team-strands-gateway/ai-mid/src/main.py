"""
AI Soccer Midfielder Agent (Gateway) — Controls ONLY player 2 (Midfielder).
Aggressive second-striker tactics + precomputed TACTICS block; MCP tools as backup.
Uses Strands SDK + Amazon Nova Micro (latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from gateway_agent_base import create_gateway_agent
from gateway_invoke_handler import create_gateway_invoke_handler
from fallback import build_fallback, MID_CONFIG

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 2
POSITION_LABEL = "MID"

SYSTEM_PROMPT = f"""Ultra-aggressive attacking midfielder AI (second striker). You control ONLY player {MY_PLAYER_ID} (MID) in 5v5 soccer. Each tick: read state, reply exactly ONE command.

DATA: the state includes a computed TACTICS block (shot odds / best passes / open space) and a SCOUTING REPORT (opponent patterns). Trust them — do NOT call MCP tools unless TACTICS is missing; answer in one turn.

TACTICS (priority order):
1. Have ball: SHOOT if within 35 of opponent goal or TACTICS says SHOOT NOW (power 1.0), else best PASS from TACTICS (prefer THROUGH to 3 or 4). Never pass back.
2. Opponent has ball: PRESS_BALL intensity 1.0 or INTERCEPT aggressive true — press high.
3. Else: MOVE_TO the open-space point from TACTICS (or advanced position near forwards), sprint true.
4. Never track back unless ball is in your own half. Goal scorer first, defender never.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | SET_STANCE(stance 0-2)
PASS/SHOOT require having the ball.

FIELD: x -55..55, y -35..35. Team 0 defends x=-55, attacks +x. Team 1 defends x=+55, attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"SHOOT","playerId":{MY_PLAYER_ID},"parameters":{{"aim_location":"TR","power":1.0}},"duration":0}}]"""

fallback_commands = build_fallback(MID_CONFIG)

agent, mcp_client = create_gateway_agent(
    SYSTEM_PROMPT, MY_PLAYER_ID, POSITION_LABEL, model_id="us.amazon.nova-micro-v1:0"
)
create_gateway_invoke_handler(
    app, agent, mcp_client, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=MID_CONFIG,
)

if __name__ == "__main__":
    app.run()
