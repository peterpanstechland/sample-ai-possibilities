"""
AI Soccer Forward 1 Agent (EXTREMELY AGGRESSIVE) — Controls ONLY player 3 (Forward 1, left striker).
Uses Strands SDK + Amazon Nova Micro.
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, FWD1_CONFIG

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 3
POSITION_LABEL = "FWD1"

# --- System Prompt ---

SYSTEM_PROMPT = f"""Ultra-aggressive striker AI. You control ONLY player {MY_PLAYER_ID} (Forward 1, left side) in 5v5 soccer. Each tick: read state, reply exactly ONE command.

RULE #1 — SHOOT, NEVER DRIBBLE: if hasBall=True and distOppGoal<=45, reply SHOOT aim CENTER power 1.0 immediately. Do NOT dribble to the byline or corner. Any open look = shoot. A hard shot beats a dribble every single time.

TACTICS (priority order):
1. hasBall=True and distOppGoal<=45: SHOOT aim CENTER power 1.0. No exceptions.
2. hasBall=True and distOppGoal>45: MOVE_TO straight at the CENTER of the opponent goal (y=0), sprint true — then shoot next tick.
3. Opponent has ball: PRESS_BALL intensity 1.0 or INTERCEPT aggressive true.
4. Else: MOVE_TO opponent penalty area (left side, y<0), sprint true. Run behind the defense, stay ready to shoot.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | SET_STANCE(stance 0-2)
PASS/SHOOT require having the ball.

FIELD: kickoff spot (0,0) at midfield. x: -55 left goal line, +55 right goal line. y: +35 top, -35 bottom. Team 0 defends x=-55 and attacks +x; Team 1 defends x=+55 and attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"SHOOT","playerId":{MY_PLAYER_ID},"parameters":{{"aim_location":"CENTER","power":1.0}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(FWD1_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=FWD1_CONFIG,
)

if __name__ == "__main__":
    app.run()
