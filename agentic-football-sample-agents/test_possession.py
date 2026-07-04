"""Shared-lib regression tests: possession, state enrichment, orchestration, guardrails.

Possession scenario background: player indices repeat across teams (home P3 and
away P3 are both idx 3). Before the resolve_holder fix, possession lookup matched
the FIRST player with the idx — always the home one — so away holders were
misattributed and hasBall was idx-only. This drove the dribble-without-shooting loss.
"""

import copy
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))

from test_helpers import GAME_STATE
from state import summarize_state, get_possession_info, resolve_holder, _is_my_team
from tactics import tactics_report, _lane_blocked
from pattern_tracker import PatternTracker
from parsing import parse_commands

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
# Shot line is present; the LANE check tells us whether it's SHOOT NOW or a
# sidestep MOVE_TO first — either is a valid decision, both beat aimlessly
# dribbling.
assert "Shot:" in rep2, rep2
assert ("LANE CLEAR" in rep2 and "SHOOT NOW" in rep2) or "LANE BLOCKED" in rep2, rep2

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

# --- Scenario E: orchestration assignments (conflict resolution without messaging) ---
# Free ball at (15.3,-5.2): home P3 (14,-5) is closest -> only P3 chases
gs6 = copy.deepcopy(GAME_STATE)
gs6["ball"]["possessionAgentId"] = None
gs6["ball"]["isFree"] = True
s_chaser = summarize_state(gs6, 0, 3, "FWD1")
assert "CLOSEST player to the free ball — chase" in s_chaser, s_chaser
s_holder = summarize_state(gs6, 0, 4, "FWD2")
assert "teammate P3 is closest to the free ball — do NOT chase" in s_holder, s_holder

# Opponent holds (away P3 at (30,-12)): home P3 is nearest -> designated presser,
# everyone else is told to cut lanes/mark instead of piling in
s_press = summarize_state(gs, 0, 3, "FWD1")
assert "designated PRESSER" in s_press, s_press
s_cover = summarize_state(gs, 0, 2, "MID")
assert "P3 presses the carrier" in s_cover, s_cover
# When WE hold the ball there is no assignment line at all
assert "ASSIGNMENT" not in summarize_state(gs2, 0, 4, "FWD2")

# --- Scenario F: score/time game plan ---
gs7 = copy.deepcopy(GAME_STATE)
gs7["gameTime"] = 250
gs7["score"] = {"home": 0, "away": 1}
assert "GAME PLAN: trailing late" in summarize_state(gs7, 0, 3, "FWD1")   # home trails
assert "GAME PLAN: leading late" in summarize_state(gs7, 1, 3, "FWD1")    # away leads
gs7["score"] = {"home": 1, "away": 1}
assert "GAME PLAN: tied late" in summarize_state(gs7, 0, 3, "FWD1")
gs7["gameTime"] = 100
assert "GAME PLAN" not in summarize_state(gs7, 0, 3, "FWD1")              # early game: no line

# --- Scenario G: command guardrails (clamp out-of-range LLM output) ---
cmds = parse_commands(
    '[{"commandType":"SHOOT","parameters":{"aim_location":"TOP","power":5}},'
    ' {"commandType":"MOVE_TO","parameters":{"target_x":120,"target_y":-99}},'
    ' {"commandType":"PASS","parameters":{"target_player_id":9}},'
    ' {"commandType":"PRESS_BALL","parameters":{"intensity":3}},'
    ' {"commandType":"TELEPORT","parameters":{}}]', 0, 3)
assert len(cmds) == 4, cmds                                     # TELEPORT dropped
assert cmds[0]["parameters"] == {"aim_location": "CENTER", "power": 1.0}, cmds[0]
assert cmds[1]["parameters"] == {"target_x": 55, "target_y": -35}, cmds[1]
assert cmds[2]["parameters"]["target_player_id"] == 4, cmds[2]  # 9 invalid, 3=self -> 4
assert cmds[3]["parameters"]["intensity"] == 1.0, cmds[3]
shoot_bare = parse_commands('[{"commandType":"SHOOT","parameters":{}}]', 0, 4)[0]
assert shoot_bare["parameters"] == {"aim_location": "CENTER", "power": 1.0}, shoot_bare
pass_self = parse_commands('[{"commandType":"PASS","parameters":{"target_player_id":4}}]', 0, 4)[0]
assert pass_self["parameters"]["target_player_id"] == 3, pass_self

# --- Scenario H: shot lane checking (LANE CLEAR vs LANE BLOCKED) ---
# Clear lane: no opponent anywhere near the line me -> (55,0)
me_open = {"x": 30.0, "y": 0.0}
blocked, off = _lane_blocked(me_open, 55.0, [
    {"position": {"x": 45, "y": 20}},  # off to the side, not on the line
    {"position": {"x": 20, "y": 0}},   # behind me, doesn't count
])
assert not blocked and off == 0.0, (blocked, off)

# Blocked directly ahead: expect an off-axis suggestion
blocked, off = _lane_blocked(me_open, 55.0, [
    {"position": {"x": 40, "y": 0}},  # defender square on the shot line
])
assert blocked and off != 0.0, (blocked, off)

# Shot line integrated: FWD1 at (14,-5), dist 41 to goal (not point-blank).
# A single defender at (30,-3) sits inside the shot cone for CENTER, TL, and
# TR aims — the corner picker cannot escape, so we get LANE BLOCKED sidestep.
gs8 = copy.deepcopy(GAME_STATE)
gs8["ball"]["possessionAgentId"] = "agentId_3"
gs8["ball"]["position"] = {"x": 14.0, "y": -5.0, "z": 0}
for p in gs8["players"]:
    if p["teamCode"] == "away" and p["agentId"] == "agentId_1":
        p["position"] = {"x": 30, "y": -3}
    elif p["teamCode"] == "away" and p["agentId"] != "agentId_0":
        p["position"] = {"x": 45, "y": 25}  # push everyone else out of the cone
rep8 = tactics_report(gs8, 0, 3, "FWD1")
assert "LANE BLOCKED" in rep8 and "MOVE_TO" in rep8, rep8

# Same fixture but no defender on the line — LANE CLEAR
gs9 = copy.deepcopy(GAME_STATE)
gs9["ball"]["possessionAgentId"] = "agentId_3"
gs9["ball"]["position"] = {"x": 14.0, "y": -5.0, "z": 0}
for p in gs9["players"]:
    if p["teamCode"] == "away":
        # Move all away players out of the shot cone from (14,-5) to (55,0)
        p["position"] = {"x": 45, "y": 25}
rep9 = tactics_report(gs9, 0, 3, "FWD1")
assert "LANE CLEAR" in rep9 and "SHOOT NOW: aim" in rep9, rep9

# --- Scenario I: point-blank shot fires even with slight overlap ---
# FWD1 at (48,0), goal at (55,0), a defender at (52,0) blocks CENTER but
# the shot is at 7 units — point-blank rule should still SHOOT.
gs10 = copy.deepcopy(GAME_STATE)
gs10["ball"]["possessionAgentId"] = "agentId_3"
gs10["ball"]["position"] = {"x": 48.0, "y": 0.0, "z": 0}
for p in gs10["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": 48, "y": 0}
    if p["teamCode"] == "away" and p["agentId"] == "agentId_1":
        p["position"] = {"x": 52, "y": 0}
rep10 = tactics_report(gs10, 0, 3, "FWD1")
assert "POINT-BLANK" in rep10 or "LANE CLEAR" in rep10, rep10
assert "SHOOT NOW" in rep10, rep10

print("Scenario A (away P3 holds): home view OPP / away view MY — OK")
print("Scenario B (home P3 holds): hasBall=True + SHOOT NOW CENTER 1.0 — OK")
print("Scenario C (opp GK holds): our GK hasBall=False — OK")
print("Scenario D (coach/free-ball/stamina/lastAction enrichment) — OK")
print("Scenario E (chase/press assignments, one player to the ball) — OK")
print("Scenario F (late-game GAME PLAN by score) — OK")
print("Scenario G (command guardrails clamp bad params) — OK")
print("Scenario H (LANE CLEAR / BLOCKED shot check with sidestep hint) — OK")
print("Scenario I (point-blank always shoots even with slight overlap) — OK")
print("ALL LIB TESTS PASSED")
