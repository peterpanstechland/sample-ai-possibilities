"""Temp verification: possession disambiguation (home P3 vs away P3 both idx 3).

Before the fix, possession lookup matched the FIRST player with the idx —
always the home one — so away holders were misattributed and hasBall was
idx-only (true for both teams). This drove the dribble-without-shooting loss.
"""

import copy
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))

from test_helpers import GAME_STATE
from state import summarize_state, get_possession_info, resolve_holder, _is_my_team
from tactics import tactics_report
from pattern_tracker import PatternTracker

# --- Scenario A: AWAY P3 holds the ball (ball at away P3's position (30,-12)) ---
gs = copy.deepcopy(GAME_STATE)
gs["ball"]["possessionAgentId"] = "agentId_3"
gs["ball"]["position"] = {"x": 30.0, "y": -12.0, "z": 0}

holder = resolve_holder(gs["ball"], gs["players"])
assert holder["teamCode"] == "away", f"holder should be away P3, got {holder['teamCode']}"

pid, status, mine = get_possession_info(gs["ball"], gs["players"], 0)
assert status == "OPP player 3" and not mine, f"team0 view wrong: {status}, mine={mine}"
pid, status, mine = get_possession_info(gs["ball"], gs["players"], 1)
assert status == "MY player 3" and mine, f"team1 view wrong: {status}, mine={mine}"

summary = summarize_state(gs, 0, 3, "FWD1")
assert "hasBall=False" in summary, "home FWD1 must NOT think it has the ball"
assert "held by OPP player 3" in summary

# home FWD1 without ball -> no Shot line, opp P3 is top threat for DEF
rep = tactics_report(gs, 0, 3, "FWD1")
assert "Shot:" not in rep, f"no shot line without ball: {rep}"
rep_def = tactics_report(gs, 0, 1, "DEF")
assert "Top threat: P3" in rep_def and "has ball" in rep_def, rep_def

# tracker counts it as opponent possession for team 0
t = PatternTracker()
for i in range(12):
    g = copy.deepcopy(gs)
    g["gameTime"] = 10 + i * 5
    t.update(g, 0)
assert t.opp_hold[3] == 12 and t.opp_hold_total == 12, dict(t.opp_hold)

# --- Scenario B: HOME P3 holds (ball at home P3's position (14,-5)) ---
gs2 = copy.deepcopy(GAME_STATE)
gs2["ball"]["possessionAgentId"] = "agentId_3"
gs2["ball"]["position"] = {"x": 14.0, "y": -5.0, "z": 0}

holder2 = resolve_holder(gs2["ball"], gs2["players"])
assert holder2["teamCode"] == "home"

summary2 = summarize_state(gs2, 0, 3, "FWD1")
assert "hasBall=True" in summary2, "home FWD1 SHOULD have the ball now"
assert "held by MY player 3" in summary2

rep2 = tactics_report(gs2, 0, 3, "FWD1")
assert "Shot:" in rep2 and "SHOOT NOW: aim CENTER power 1.0" in rep2, rep2

# --- Scenario C: GK ambiguity (both GKs are idx 0; opp GK holds at (50,0)) ---
gs3 = copy.deepcopy(GAME_STATE)
gs3["ball"]["possessionAgentId"] = "agentId_0"
gs3["ball"]["position"] = {"x": 50.0, "y": 0.0, "z": 0}
summary3 = summarize_state(gs3, 0, 0, "GK")
assert "hasBall=False" in summary3, "our GK must not think it holds the opponent GK's ball"

# --- Scenario D: state enrichment (coach orders, free ball, stamina, lastAction) ---
gs4 = copy.deepcopy(GAME_STATE)
gs4["ball"]["possessionAgentId"] = None
gs4["ball"]["isFree"] = True
gs4["ball"]["velocity"] = {"x": 3.0, "y": -1.0, "z": 0}
gs4["teamChat"] = [{"message": "全员压上，多射门"}]
gs4["playMode"] = "FREE_KICK"
for p in gs4["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["stamina"] = 10
        p["lastAction"] = "MOVE_TO"
summary4 = summarize_state(gs4, 0, 3, "FWD1")
assert "FREE ball" in summary4 and "heading to" in summary4, summary4
assert "COACH ORDER" in summary4 and "全员压上" in summary4, summary4
assert "RESTART (FREE_KICK)" in summary4, summary4
assert "LOW STAMINA" in summary4, summary4
assert "lastAction=MOVE_TO" in summary4, summary4

# string-typed teamChat entries also work; no coach line when chat empty
gs5 = copy.deepcopy(GAME_STATE)
gs5["teamChat"] = ["press high"]
assert "COACH ORDER (obey immediately, overrides tactics): press high" in summarize_state(gs5, 0, 3, "FWD1")
assert "COACH ORDER" not in summarize_state(GAME_STATE, 0, 3, "FWD1")

print("Scenario A (away P3 holds): home view OPP / away view MY — OK")
print("Scenario B (home P3 holds): hasBall=True + SHOOT NOW CENTER 1.0 — OK")
print("Scenario C (opp GK holds): our GK hasBall=False — OK")
print("Scenario D (coach/free-ball/stamina/lastAction enrichment) — OK")
print("ALL POSSESSION TESTS PASSED")
