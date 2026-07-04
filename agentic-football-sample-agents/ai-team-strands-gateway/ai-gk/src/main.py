"""
AI Soccer Goalkeeper Agent (Gateway) — Controls ONLY player 0 (Goalkeeper).
Aggressive sweeper-keeper tactics + precomputed TACTICS block; MCP tools as backup.
Uses Strands SDK + Amazon Nova Micro (latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from gateway_agent_base import create_gateway_agent
from gateway_invoke_handler import create_gateway_invoke_handler
from fallback import build_fallback, GK_CONFIG

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 0
POSITION_LABEL = "GK"

SYSTEM_PROMPT = f"""Ultra-aggressive sweeper-keeper AI. You control ONLY player {MY_PLAYER_ID} (GK) in 5v5 soccer. Each tick: read state, reply exactly ONE command.

DATA: the state includes a computed TACTICS block (top threat / pass odds) and a SCOUTING REPORT (opponent patterns). Trust them — do NOT call MCP tools unless TACTICS is missing; answer in one turn.

TACTICS (priority order):
1. Have ball near own goal: GK_DISTRIBUTE method KICK to player 3 or 4 (use best-pass data if given).
2. hasBall=True elsewhere: SHOOT aim CENTER power 1.0 if within 45 of opponent goal, else PASS type THROUGH to 3 or 4.
3. Opponent has ball in your half: PRESS_BALL intensity 1.0 or INTERCEPT aggressive true.
4. Else: MOVE_TO halfway line (x=0), sprint true. Push up, you are an extra attacker.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | GK_DISTRIBUTE(target_player_id,method=THROW|KICK) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | SET_STANCE(stance 0-2)
PASS/SHOOT/GK_DISTRIBUTE require having the ball.

FIELD: x -55..55, y -35..35. Team 0 defends x=-55, attacks +x. Team 1 defends x=+55, attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"GK_DISTRIBUTE","playerId":{MY_PLAYER_ID},"parameters":{{"target_player_id":3,"method":"KICK"}},"duration":0}}]"""

fallback_commands = build_fallback(GK_CONFIG)

agent, mcp_client = create_gateway_agent(
    SYSTEM_PROMPT, MY_PLAYER_ID, POSITION_LABEL, model_id="us.amazon.nova-micro-v1:0"
)
create_gateway_invoke_handler(
    app, agent, mcp_client, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=GK_CONFIG,
)

if __name__ == "__main__":
    app.run()
