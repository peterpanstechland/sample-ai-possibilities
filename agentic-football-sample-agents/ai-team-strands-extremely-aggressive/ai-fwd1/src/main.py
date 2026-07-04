"""
AI Soccer Forward 1 Agent (EXTREMELY AGGRESSIVE) — Controls ONLY player 3 (Forward 1, left striker).
Uses Strands SDK + Amazon Nova Micro.
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from dataclasses import replace
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, FWD1_CONFIG

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 3
POSITION_LABEL = "FWD1"

# --- System Prompt ---

SYSTEM_PROMPT = f"""Ultra-aggressive left striker AI. You control ONLY player {MY_PLAYER_ID} (FWD1) in 5v5 soccer. Each tick: read state, reply ONE command.

RULE #1 — SHOOT INTO THE CLEAR LANE. Read the TACTICS "Shot" line every tick and OBEY it verbatim:
- "LANE CLEAR (X)": SHOOT aim X power 1.0 (X is CENTER, TL, TR, BL, or BR).
- "POINT-BLANK": SHOOT aim CENTER power 1.0.
- "LANE BLOCKED all corners — first MOVE_TO (x,y)": reply exactly that MOVE_TO (side-step), then shoot next tick.
- "LANE BLOCKED all corners — PASS": PASS type THROUGH to player 4 (or 2 if 4 is marked).
- "out of range": sprint toward the wing target in rule 5, do NOT run down the center.
A shot into a clear corner or a point-blank blast beats every dribble EVERY TIME.

TACTICS (priority order):
1. hasBall=True and distOppGoal<=45: obey the TACTICS Shot line (SHOOT or side-step MOVE_TO).
2. hasBall=True and distOppGoal>45: MOVE_TO the LEFT wing edge of the opponent box (x = opp_goal_x*0.75, y = -14), sprint true — DO NOT run down the center, that is a defender highway.
3. Opponent has ball AND ASSIGNMENT says you are the presser: PRESS_BALL intensity 1.0 (or SLIDE_TACKLE if within 2).
4. Opponent has ball AND ASSIGNMENT says a teammate presses: MARK the nearest opponent forward (tightness TIGHT) — do NOT go press yourself.
5. Teammate 4 has the ball: sprint to the FAR POST (x ≈ opp_goal_x - 6, y = -6) for the tap-in.
6. Free ball AND ASSIGNMENT says you are closest: MOVE_TO the ball, sprint true.
7. Else: MOVE_TO the left half-space between opponent DEF and MID (x = opp_goal_x*0.5, y = -14), sprint true.

RESPECT ASSIGNMENT lines exactly — never five players chasing one ball.
Never PASS backward. Never dribble into the center of the pitch. Never SET_STANCE unless forced.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | MARK(target_player_id,tightness=LOOSE|TIGHT) | SET_STANCE(stance 0-2)

FIELD: kickoff (0,0). x: -55 own-goal-line to +55 opp-goal-line. y: -35 bottom to +35 top. Team 0 defends x=-55 and attacks +x; Team 1 defends x=+55 and attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"SHOOT","playerId":{MY_PLAYER_ID},"parameters":{{"aim_location":"CENTER","power":1.0}},"duration":0}}]"""


# --- Fallback ---
# Aggressive-team specific: only the designated player presses (no 5-on-1 mob);
# non-pressers MARK; forwards attack the wing (y=-14), not the center.
AGG_FWD1_CONFIG = replace(
    FWD1_CONFIG,
    press_only_if_designated=True,
    press_distance=10.0,
    off_ball_action="MARK",
    advance_y=-14.0, default_y=-14.0, support_y=-14.0,
    advance_x_factor=0.75, support_x_factor=0.6,
)
fallback_commands = build_fallback(AGG_FWD1_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=AGG_FWD1_CONFIG,
)

if __name__ == "__main__":
    app.run()
