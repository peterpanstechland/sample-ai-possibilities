"""
AI Soccer Goalkeeper Agent (Memory) — Controls ONLY player 0 (Goalkeeper).
Aggressive sweeper-keeper tactics + AgentCore Memory for cross-tick recall.
Uses Strands SDK + Amazon Nova Micro (latency-optimized).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

# memory_agent_base lives one level above src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from memory_agent_base import create_memory_agent
from agent_base import create_invoke_handler
from fallback import build_fallback, GK_CONFIG

app = BedrockAgentCoreApp()

MY_PLAYER_ID = 0
POSITION_LABEL = "GK"

SYSTEM_PROMPT = f"""Ultra-aggressive sweeper-keeper AI. You control ONLY player {MY_PLAYER_ID} (GK) in 5v5 soccer. Each tick: read state, reply exactly ONE command.

MEMORY: your recent ticks are in this conversation; a SCOUTING REPORT summarizes match-long opponent patterns. Use them: shade toward their favored attacking side, step out early on their main threat, adapt risk to the score.

TACTICS (priority order):
1. Have ball near own goal: GK_DISTRIBUTE method KICK to player 3 or 4.
2. Have ball elsewhere: SHOOT if within 35 of opponent goal, else PASS type THROUGH to 3 or 4.
3. Opponent has ball in your half: PRESS_BALL intensity 1.0 or INTERCEPT aggressive true.
4. Else: MOVE_TO halfway line (x=0), sprint true. Push up, you are an extra attacker.

COMMANDS: MOVE_TO(target_x,target_y,sprint) | PASS(target_player_id,type=GROUND|AERIAL|THROUGH) | SHOOT(aim_location=TL|TR|BL|BR|CENTER,power) | GK_DISTRIBUTE(target_player_id,method=THROW|KICK) | PRESS_BALL(intensity) | INTERCEPT(aggressive) | SLIDE_TACKLE(target_player_id,sprint,distance) | SET_STANCE(stance 0-2)
PASS/SHOOT/GK_DISTRIBUTE require having the ball.

FIELD: x -55..55, y -35..35. Team 0 defends x=-55, attacks +x. Team 1 defends x=+55, attacks -x.

Reply ONLY the JSON array, no other text:
[{{"commandType":"GK_DISTRIBUTE","playerId":{MY_PLAYER_ID},"parameters":{{"target_player_id":3,"method":"KICK"}},"duration":0}}]"""

fallback_commands = build_fallback(GK_CONFIG)

agent = create_memory_agent(SYSTEM_PROMPT, MY_PLAYER_ID, POSITION_LABEL, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=GK_CONFIG,
)

if __name__ == "__main__":
    app.run()
