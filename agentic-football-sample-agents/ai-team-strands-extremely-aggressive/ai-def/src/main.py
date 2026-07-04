"""
AI Soccer Defender Agent (EXTREMELY AGGRESSIVE) — Controls ONLY player 1 (Defender).
Uses Strands SDK + Amazon Nova Micro (fastest model, latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, DEF_CONFIG

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 1
POSITION_LABEL = "DEF"

# --- System Prompt ---

SYSTEM_PROMPT = f"""Ultra-aggressive attacking defender AI. You control ONLY player {MY_PLAYER_ID} (DEF) in 5v5 soccer. Each tick: read state, reply exactly ONE command.

RULE #1 — SHOOT, NEVER DRIBBLE: if hasBall=True and within 45 of opponent goal, reply SHOOT aim CENTER power 1.0 immediately. Never dribble to the byline.

TACTICS (priority order):
1. hasBall=True within 45 of opponent goal: SHOOT aim CENTER power 1.0. Otherwise PASS type THROUGH forward to player 3 or 4. Never pass back.
2. Opponent has ball: PRESS_BALL intensity 1.0, INTERCEPT aggressive true, or SLIDE_TACKLE if very close.
3. Team has ball: MOVE_TO opponent half, sprint true — join every attack.
4. Only defend deep if ball is in your defensive third.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | MARK(target_player_id,tightness=LOOSE|TIGHT) | SET_STANCE(stance 0-2)
PASS/SHOOT require having the ball.

FIELD: kickoff spot (0,0) at midfield. x: -55 left goal line, +55 right goal line. y: +35 top, -35 bottom. Team 0 defends x=-55 and attacks +x; Team 1 defends x=+55 and attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"MOVE_TO","playerId":{MY_PLAYER_ID},"parameters":{{"target_x":30,"target_y":0,"sprint":true}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(DEF_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=DEF_CONFIG,
)

if __name__ == "__main__":
    app.run()
