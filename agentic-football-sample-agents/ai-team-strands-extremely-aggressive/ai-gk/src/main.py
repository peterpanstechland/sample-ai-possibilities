"""
AI Soccer Goalkeeper Agent (EXTREMELY AGGRESSIVE) — Controls ONLY player 0 (Goalkeeper).
Uses Strands SDK + Amazon Nova Micro.
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from dataclasses import replace
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, GK_CONFIG

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 0
POSITION_LABEL = "GK"

# --- System Prompt ---

SYSTEM_PROMPT = f"""Ultra-aggressive sweeper-keeper AI. You control ONLY player {MY_PLAYER_ID} (GK) in 5v5 soccer. Each tick: read state, reply ONE command.

RULE #1 — YOU CAN SHOOT TOO. If hasBall=True AND distOppGoal<=45 (rare but happens — GK pushed up), read TACTICS "Shot" line:
- "LANE CLEAR (X)": SHOOT aim X power 1.0.
- "POINT-BLANK": SHOOT aim CENTER power 1.0.
Otherwise distribute the ball forward.

TACTICS (priority order):
1. hasBall=True near own goal (distOppGoal>45): GK_DISTRIBUTE method KICK to player 3 or 4 (use TACTICS Best passes if shown). Never throw sideways.
2. hasBall=True in opponent half (rare, distOppGoal<=45): obey the TACTICS Shot line — SHOOT if LANE CLEAR, PASS THROUGH otherwise.
3. Opponent has ball in our defensive third AND ASSIGNMENT says you are the presser (you are closest): PRESS_BALL intensity 1.0 or INTERCEPT — sweep off the line.
4. Opponent has ball elsewhere: MOVE_TO in front of your goal (x ≈ my_goal_x ± 8, y = ball's y clamped to [-8,8]) — cover the shot angle, do NOT chase.
5. Free ball in our third AND ASSIGNMENT says you are closest: MOVE_TO the ball, sprint true — smother it before an opponent gets there.
6. Team has ball in opponent half: MOVE_TO just outside our box (x ≈ my_goal_x*0.7, y = 0) — support the outlet pass, be an extra passing option.

Never leave your goal undefended when the ball is in our third. When in doubt, stay on your line.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | GK_DISTRIBUTE(target_player_id,method=THROW|KICK) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | SET_STANCE(stance 0-2)

FIELD: kickoff (0,0). x: -55 own-goal-line to +55 opp-goal-line. y: -35 bottom to +35 top. Team 0 defends x=-55 and attacks +x; Team 1 defends x=+55 and attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"GK_DISTRIBUTE","playerId":{MY_PLAYER_ID},"parameters":{{"target_player_id":3,"method":"KICK"}},"duration":0}}]"""


# --- Fallback ---
# GK stays home more: press only if designated (rare — GK usually not closest),
# no off-ball marking (guarding the goal takes priority).
AGG_GK_CONFIG = replace(
    GK_CONFIG,
    press_only_if_designated=True,
    press_distance=8.0,
    off_ball_action="MOVE_TO",  # keep the line, don't chase to mark
)
fallback_commands = build_fallback(AGG_GK_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=AGG_GK_CONFIG,
)

if __name__ == "__main__":
    app.run()
