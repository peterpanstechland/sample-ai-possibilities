"""
AI Soccer Defender Agent (EXTREMELY AGGRESSIVE) — Controls ONLY player 1 (Defender).
Uses Strands SDK + Amazon Nova Micro (fastest model, latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from dataclasses import replace
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, DEF_CONFIG
from overrides import OverrideConfig

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 1
POSITION_LABEL = "DEF"

# --- System Prompt ---

SYSTEM_PROMPT = f"""Ultra-aggressive attacking defender AI (libero). You control ONLY player {MY_PLAYER_ID} (DEF) in 5v5 soccer. Each tick: read state, reply ONE command.

RULE #1 — YES, YOU CAN SHOOT. Every position shoots when the lane is clear.
- "LANE CLEAR (X)": SHOOT aim X power 1.0 (even from range).
- "POINT-BLANK": SHOOT aim CENTER power 1.0.
- "LANE BLOCKED all corners — first MOVE_TO (x,y)": reply that MOVE_TO (side-step), shoot next tick.
- "LANE BLOCKED all corners — PASS": PASS type THROUGH to a forward (3 or 4). Never PASS back to GK.

TACTICS (priority order):
1. hasBall=True and distOppGoal<=45: obey the TACTICS Shot line.
2. hasBall=True elsewhere: PASS type THROUGH to player 3 or 4 (use TACTICS "Best passes" if shown). Never dribble backward, never pass to GK.
3. Opponent has ball AND ASSIGNMENT says you press: PRESS_BALL intensity 1.0 or SLIDE_TACKLE if within 2.
4. Opponent has ball AND ASSIGNMENT says a teammate presses: MARK the opponent's most dangerous player (see TACTICS "Top threat") tightness TIGHT. Cut passing lanes rather than chasing.
5. Team has ball: MOVE_TO just past the halfway line (x ≈ 8 toward opp goal, y = 0), sprint true — you are the safety valve for clearances.
6. Free ball AND ASSIGNMENT says you are closest: MOVE_TO the ball, sprint true.
7. Only sit deep (defensive third) if ball is in your defensive third AND opponent has it.

RESPECT ASSIGNMENT lines — do NOT press when a teammate is designated presser; MARK instead.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | MARK(target_player_id,tightness=LOOSE|TIGHT) | SET_STANCE(stance 0-2)

FIELD: kickoff (0,0). x: -55 own-goal-line to +55 opp-goal-line. y: -35 bottom to +35 top. Team 0 defends x=-55 and attacks +x; Team 1 defends x=+55 and attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"MOVE_TO","playerId":{MY_PLAYER_ID},"parameters":{{"target_x":10,"target_y":0,"sprint":true}},"duration":0}}]"""


# --- Fallback ---
# Aggressive DEF: possession action becomes SHOOT_OR_PASS so a lucky clearance
# from range still ends in a shot; press only when designated; MARK when off.
AGG_DEF_CONFIG = replace(
    DEF_CONFIG,
    possession_action="SHOOT_OR_PASS",
    press_only_if_designated=True,
    press_distance=10.0,
    off_ball_action="MARK",
    default_x_factor=0.2, default_x_ref="my_goal",  # sit closer to halfway when off ball
    default_y=0,
)
fallback_commands = build_fallback(AGG_DEF_CONFIG)

# Hard tactical rules enforced in code: always shoot a clear lane, never
# chase when not designated, hold the ball-shifted defensive line (the
# anchor clamp is what actually keeps the back line compact).
OVERRIDE_CONFIG = OverrideConfig()


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=AGG_DEF_CONFIG,
    override_cfg=OVERRIDE_CONFIG,
)

if __name__ == "__main__":
    app.run()
