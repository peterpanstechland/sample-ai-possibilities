"""Local test for the classic MID agent — vanilla prompt, no overrides."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from test_helpers import mock_agentcore, GAME_STATE, TEAM_ID
mock_agentcore()

from state import summarize_state
from parsing import parse_commands
from main import fallback_commands, MY_PLAYER_ID, POSITION_LABEL


def test_summarize():
    print(f"=== STATE SUMMARY ({POSITION_LABEL}, player {MY_PLAYER_ID}) ===")
    print(summarize_state(GAME_STATE, TEAM_ID, MY_PLAYER_ID, POSITION_LABEL))
    print()


def test_fallback():
    cmds = fallback_commands(GAME_STATE, TEAM_ID, MY_PLAYER_ID)
    for c in cmds:
        print(f"  P{c['playerId']}: {c['commandType']} {c.get('parameters', {})}")
    assert all(c["playerId"] == MY_PLAYER_ID for c in cmds)
    print("  fallback OK")


def test_fallback_with_ball():
    state = json.loads(json.dumps(GAME_STATE))
    state["ball"]["possessionAgentId"] = "agentId_2"
    state["ball"]["position"] = {"x": 25.0, "y": 0.0, "z": 0}
    for p in state["players"]:
        if p["teamCode"] == "home" and p["agentId"] == "agentId_2":
            p["position"] = {"x": 25, "y": 0}
    cmds = fallback_commands(state, TEAM_ID, MY_PLAYER_ID)
    assert cmds[0]["commandType"] in ("SHOOT", "PASS"), cmds[0]
    print(f"  with ball: {cmds[0]['commandType']} OK")


def test_parse():
    resp = '[{"commandType":"SHOOT","playerId":2,"parameters":{"aim_location":"TR","power":1.0},"duration":0}]'
    cmds = parse_commands(resp, TEAM_ID, MY_PLAYER_ID)
    assert len(cmds) == 1 and cmds[0]["playerId"] == MY_PLAYER_ID
    print("  parse OK")


if __name__ == "__main__":
    test_summarize()
    test_fallback()
    test_fallback_with_ball()
    test_parse()
    print("Classic MID local tests OK")
