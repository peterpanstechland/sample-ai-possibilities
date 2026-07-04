"""
AI Soccer Midfielder Agent (EXTREMELY AGGRESSIVE) — Controls ONLY player 2 (Midfielder).
Uses Strands SDK + Amazon Nova Micro (fastest model, latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from dataclasses import replace
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, MID_CONFIG
from overrides import OverrideConfig

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 2
POSITION_LABEL = "MID"

# --- System Prompt ---

SYSTEM_PROMPT = f"""Ultra-aggressive attacking midfielder AI (second striker). You control ONLY player {MY_PLAYER_ID} (MID) in 5v5 soccer. Each tick: read state, reply ONE command.

RULE #1 — SHOOT INTO THE CLEAR LANE. Read the TACTICS "Shot" line every tick:
- "LANE CLEAR (X)": SHOOT aim X power 1.0 (CENTER / TL / TR / BL / BR).
- "POINT-BLANK": SHOOT aim CENTER power 1.0.
- "LANE BLOCKED all corners — first MOVE_TO (x,y)": reply that MOVE_TO (side-step), shoot next tick.
- "LANE BLOCKED all corners — PASS": PASS type THROUGH to a forward (3 or 4, pick whoever has more space in TACTICS Best passes).
- "out of range": sprint into the D of the box (x=opp_goal_x*0.7, y=0).

TACTICS (priority order):
1. hasBall=True and distOppGoal<=45: obey the TACTICS Shot line.
2. hasBall=True and distOppGoal>45: MOVE_TO the top-of-the-box arc (x = opp_goal_x*0.7, y = 0), sprint true — you are the second striker, arrive to shoot.
3. Opponent has ball AND ASSIGNMENT says you press: PRESS_BALL intensity 1.0 (or INTERCEPT).
4. Opponent has ball AND ASSIGNMENT says a teammate presses: MARK the opponent midfielder (usually P2 opp) TIGHT — kill their build-up.
5. Free ball AND ASSIGNMENT says you are closest: MOVE_TO the ball, sprint true.
6. Teammate 3 or 4 has the ball: trail ~8 behind them at the D of the box (x = opp_goal_x*0.6, y toward the ball carrier's opposite side) for the layoff/rebound. Never crowd them.
7. Else: MOVE_TO advanced central position (x = opp_goal_x*0.4, y = 0), sprint true.

RESPECT ASSIGNMENT lines exactly. Never PASS backward. Never SET_STANCE unless forced.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | MARK(target_player_id,tightness=LOOSE|TIGHT) | SET_STANCE(stance 0-2)

FIELD: kickoff (0,0). x: -55 own-goal-line to +55 opp-goal-line. y: -35 bottom to +35 top. Team 0 defends x=-55 and attacks +x; Team 1 defends x=+55 and attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"SHOOT","playerId":{MY_PLAYER_ID},"parameters":{{"aim_location":"CENTER","power":1.0}},"duration":0}}]"""


# --- Fallback ---
AGG_MID_CONFIG = replace(
    MID_CONFIG,
    press_only_if_designated=True,
    press_distance=10.0,
    off_ball_action="MARK",
)
fallback_commands = build_fallback(AGG_MID_CONFIG)

# Hard tactical rules enforced in code: always shoot a clear lane, never
# chase when not designated, hold the compact midfield line when defending.
OVERRIDE_CONFIG = OverrideConfig()


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=AGG_MID_CONFIG,
    override_cfg=OVERRIDE_CONFIG,
)

if __name__ == "__main__":
    app.run()
