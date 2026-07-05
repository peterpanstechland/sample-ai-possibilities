"""Local test for the classic DEF agent — vanilla prompt, no overrides."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from test_helpers import mock_agentcore, GAME_STATE, TEAM_ID
mock_agentcore()

from state import summarize_state
from parsing import parse_commands
from main import fallback_commands, MY_PLAYER_ID, POSITION_LABEL, SYSTEM_PROMPT


def test_summarize():
    print(f"=== STATE SUMMARY ({POSITION_LABEL}, player {MY_PLAYER_ID}) ===")
    summary = summarize_state(GAME_STATE, TEAM_ID, MY_PLAYER_ID, POSITION_LABEL)
    print(summary)
    print()


def test_fallback():
    print(f"=== FALLBACK ({POSITION_LABEL}) ===")
    cmds = fallback_commands(GAME_STATE, TEAM_ID, MY_PLAYER_ID)
    for c in cmds:
        print(f"  P{c['playerId']}: {c['commandType']} {c.get('parameters', {})}")
    assert all(c["playerId"] == MY_PLAYER_ID for c in cmds)
    print()


def test_fallback_with_ball():
    print(f"=== FALLBACK WITH BALL ({POSITION_LABEL}) ===")
    state = json.loads(json.dumps(GAME_STATE))
    state["ball"]["possessionAgentId"] = f"agentId_{MY_PLAYER_ID}"
    state["ball"]["position"] = {"x": 25.0, "y": 0.0, "z": 0}
    for p in state["players"]:
        if p["teamCode"] == "home" and p["agentId"] == f"agentId_{MY_PLAYER_ID}":
            p["position"] = {"x": 25, "y": 0}
    cmds = fallback_commands(state, TEAM_ID, MY_PLAYER_ID)
    for c in cmds:
        print(f"  P{c['playerId']}: {c['commandType']} {c.get('parameters', {})}")
    assert cmds[0]["commandType"] in ("SHOOT", "PASS"), cmds[0]
    print()


def test_parse():
    print("=== PARSE TESTS ===")
    resp = '[{"commandType":"PRESS_BALL","playerId":1,"parameters":{"intensity":0.95},"duration":5}]'
    cmds = parse_commands(resp, TEAM_ID, MY_PLAYER_ID)
    assert len(cmds) == 1 and cmds[0]["playerId"] == MY_PLAYER_ID
    print("  PASS")
    print()


if __name__ == "__main__":
    test_summarize()
    test_fallback()
    test_fallback_with_ball()
    test_parse()
    print("Classic DEF local tests OK")
