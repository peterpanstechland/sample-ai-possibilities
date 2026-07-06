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
from tactics import tactics_report, _lane_blocked, shot_power
from pattern_tracker import PatternTracker
from parsing import parse_commands
from overrides import OverrideConfig, apply_overrides
import math

def _d_goal(pos, opp_goal_x=55.0):
    return math.hypot(opp_goal_x - pos.get("x", 0), pos.get("y", 0))

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

# Nova 2 Lite emits unevaluated arithmetic in number slots — folded, not dropped
lite_arith = parse_commands(
    '```json\n[{"commandType":"MOVE_TO","playerId":4,'
    '"parameters":{"target_x":-55*0.5,"target_y":14,"sprint":true},"duration":0}]\n```',
    0, 4)
assert lite_arith and lite_arith[0]["parameters"]["target_x"] == -27.5, lite_arith
lite_arith2 = parse_commands(
    '[{"commandType":"MOVE_TO","parameters":{"target_x":55*0.75,"target_y":-14}}]', 0, 3)
assert lite_arith2 and lite_arith2[0]["parameters"]["target_x"] == 41.25, lite_arith2
# plain numbers and strings pass through the folder untouched
assert parse_commands('[{"commandType":"MOVE_TO","parameters":{"target_x":40.5,"target_y":-8}}]',
                      0, 3)[0]["parameters"]["target_x"] == 40.5

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

# --- Scenario J: post-LLM tactical overrides (code enforces the game plan) ---
OV = OverrideConfig()

def _mk(ctype, **params):
    return [{"commandType": ctype, "playerId": 3, "teamId": 0, "parameters": params}]

# J1: holder in range but CENTER lane blocked -> still SHOOT (shoot-first).
out, tag = apply_overrides(_mk("MOVE_TO", target_x=30, target_y=0, sprint=True),
                           gs2, 0, 3, "FWD1", OV)
assert tag == "shoot" and out[0]["commandType"] == "SHOOT", (tag, out)
assert out[0]["parameters"]["aim_location"] == "CENTER"

# J1b: clear CENTER lane -> immediate SHOOT CENTER.
gsJ1b = copy.deepcopy(GAME_STATE)
gsJ1b["ball"]["possessionAgentId"] = "agentId_3"
gsJ1b["ball"]["position"] = {"x": 14.0, "y": -5.0, "z": 0}
for p in gsJ1b["players"]:
    if p["teamCode"] == "away":
        p["position"] = {"x": 45, "y": 25}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=30, target_y=0, sprint=True),
                           gsJ1b, 0, 3, "FWD1", OV)
assert tag == "shoot" and out[0]["commandType"] == "SHOOT", (tag, out)
assert out[0]["parameters"]["aim_location"] == "CENTER"

# J2: LLM SHOOT in range while lane blocked -> still SHOOT CENTER (never downgrade).
out, tag = apply_overrides(_mk("SHOOT", aim_location="CENTER", power=0.5),
                           gs2, 0, 3, "FWD1", OV)
assert tag in ("shoot", "aim") and out[0]["commandType"] == "SHOOT", (tag, out)
assert out[0]["parameters"]["aim_location"] == "CENTER"

# J3: opponent holds (gs: away P3 at (30,-12)); home P4 is NOT the designated
# presser (home P3 is closer) — its PRESS_BALL becomes a MARK on the nearest
# non-holder opponent (away P2).
cmds4 = [{"commandType": "PRESS_BALL", "playerId": 4, "teamId": 0,
          "parameters": {"intensity": 1.0}}]
out, tag = apply_overrides(cmds4, gs, 0, 4, "FWD2", OV)
assert tag == "no-chase" and out[0]["commandType"] == "MARK", (tag, out)
assert out[0]["parameters"]["target_player_id"] in (1, 2), out

# J4: the designated presser (home P3, closest to the carrier) keeps pressing.
out, tag = apply_overrides(_mk("PRESS_BALL", intensity=1.0), gs, 0, 3, "FWD1", OV)
assert tag is None and out[0]["commandType"] == "PRESS_BALL", (tag, out)

# J5: defensive phase, MID wanders far from anchor -> pulled to the mid block.
cmds2 = [{"commandType": "MOVE_TO", "playerId": 2, "teamId": 0,
          "parameters": {"target_x": 45, "target_y": 20, "sprint": True}}]
out, tag = apply_overrides(cmds2, gs, 0, 2, "MID", OV)
assert tag in ("anchor", "hold-line", "mark-near"), (tag, out)
assert out[0]["commandType"] == "MOVE_TO", out
assert -33 <= out[0]["parameters"]["target_x"] <= -17, out

# J6: teammate holds the ball but the agent answers PRESS_BALL -> support run.
out, tag = apply_overrides([{"commandType": "PRESS_BALL", "playerId": 4, "teamId": 0,
                             "parameters": {"intensity": 1.0}}], gs2, 0, 4, "FWD2", OV)
assert tag == "support" and out[0]["commandType"] == "MOVE_TO", (tag, out)
assert out[0]["parameters"]["target_x"] == 42, out  # penalty-spot area, not a chase

# J7: carrying out of range down the middle -> steered to the wing lane.
gs11 = copy.deepcopy(GAME_STATE)
gs11["ball"]["possessionAgentId"] = "agentId_3"
gs11["ball"]["position"] = {"x": -20.0, "y": -5.0, "z": 0}
for p in gs11["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": -20, "y": -5}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=0, target_y=0, sprint=True),
                           gs11, 0, 3, "FWD1", OverrideConfig(wing_y=-14.0))
assert tag == "wing" and out[0]["parameters"]["target_y"] == -14.0, (tag, out)

# J8: GK holds the line under overrides; None config is still a no-op.
out, tag = apply_overrides([{"commandType": "MOVE_TO", "playerId": 0, "teamId": 0,
                             "parameters": {"target_x": 0, "target_y": 0}}], gs, 0, 0, "GK", OV)
assert tag == "gk-line" and out[0]["parameters"]["target_x"] == -52.8, (tag, out)
out, tag = apply_overrides(_mk("MOVE_TO", target_x=30, target_y=0), gs2, 0, 3, "FWD1", None)
assert tag is None and out[0]["commandType"] == "MOVE_TO"

# --- Scenario K: iter-9 counter-attack + GK/DEF blast rule ---
BLAST = OverrideConfig(always_blast=True)

def _mk_for(pid, ctype, **params):
    return [{"commandType": ctype, "playerId": pid, "teamId": 0, "parameters": params}]

# K1: DEF holds deep in our half (dist ~90 to goal) and tries to PASS -> blast
# with scaled power so the clearance stays on frame.
gsK1 = copy.deepcopy(GAME_STATE)
gsK1["ball"]["possessionAgentId"] = "agentId_1"
gsK1["ball"]["position"] = {"x": -35.0, "y": 5.0, "z": 0}
for p in gsK1["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_1":
        p["position"] = {"x": -35, "y": 5}
out, tag = apply_overrides(_mk_for(1, "PASS", target_player_id=3, type="GROUND"),
                           gsK1, 0, 1, "DEF", BLAST)
assert tag in ("blast", "gk-clear", "gk-blast") and out[0]["commandType"] == "SHOOT", (tag, out)
assert out[0]["parameters"]["power"] >= 0.95, out
# DEF TACTICS line agrees: BLAST verdict, no range gate
repK1 = tactics_report(gsK1, 0, 1, "DEF")
assert "BLAST" in repK1 and "SHOOT NOW" in repK1, repK1

# K2: GK conservative — safe possession distributes; goal-kick under pressure blasts.
gsK2 = copy.deepcopy(GAME_STATE)
gsK2["ball"]["possessionAgentId"] = "agentId_0"
gsK2["ball"]["position"] = {"x": -50.0, "y": 0.0, "z": 0}
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsK2, 0, 0, "GK", BLAST)
assert tag in ("gk-dist", "gk-launch", "gk-restart") and out[0]["commandType"] == "GK_DISTRIBUTE", (tag, out)
gsK2["playMode"] = "GOAL_KICK"
for p in gsK2["players"]:
    if p["teamCode"] == "away" and p["agentId"] == "agentId_1":
        p["position"] = {"x": -45, "y": 1}
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=4, method="KICK"),
                           gsK2, 0, 0, "GK", BLAST)
assert tag == "gk-blast" and out[0]["commandType"] == "SHOOT", (tag, out)

# K3: long shot enforcement — holder at dist 48 (45-52 window), opponent GK
# way off his line (22 from goal), lane clear -> forced full-power shot.
gsK3 = copy.deepcopy(GAME_STATE)
gsK3["ball"]["possessionAgentId"] = "agentId_3"
gsK3["ball"]["position"] = {"x": 7.0, "y": 0.0, "z": 0}
posK3 = {"agentId_0": (35, 10), "agentId_1": (-20, 10), "agentId_2": (30, 20),
         "agentId_3": (20, -15), "agentId_4": (40, -18)}
for p in gsK3["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": 7, "y": 0}
    elif p["teamCode"] == "away":
        x, y = posK3[p["agentId"]]
        p["position"] = {"x": x, "y": y}
out, tag = apply_overrides(_mk_for(3, "MOVE_TO", target_x=20, target_y=0, sprint=True),
                           gsK3, 0, 3, "FWD1", OverrideConfig())
assert tag in ("shoot", "snap-shot") and out[0]["commandType"] == "SHOOT", (tag, out)
aim_k3 = out[0]["parameters"]["aim_location"]
assert out[0]["parameters"]["power"] == shot_power(_d_goal({"x": 7, "y": 0}), aim_k3)

# K4: counter-attack outlet — 4 opponents committed into OUR half, MID holds
# deep (dist 85) and panic-blasts -> rewritten to ONE fast THROUGH pass to the
# most advanced forward with a clear lane (home P4).
gsK4 = copy.deepcopy(GAME_STATE)
gsK4["ball"]["possessionAgentId"] = "agentId_2"
gsK4["ball"]["position"] = {"x": -30.0, "y": 0.0, "z": 0}
posK4_home = {"agentId_0": (-50, 0), "agentId_1": (-40, -5), "agentId_2": (-30, 0),
              "agentId_3": (5, -10), "agentId_4": (10, 10)}
posK4_away = {"agentId_0": (50, 0), "agentId_1": (-20, 10), "agentId_2": (-25, 15),
              "agentId_3": (-5, 15), "agentId_4": (-15, -20)}
for p in gsK4["players"]:
    x, y = (posK4_home if p["teamCode"] == "home" else posK4_away)[p["agentId"]]
    p["position"] = {"x": x, "y": y}
# high-press detection feeds the state summary…
assert "OPP HIGH PRESS" in summarize_state(gsK4, 0, 2, "MID")
# …and the override turns the panic blast into the outlet pass
out, tag = apply_overrides(_mk_for(2, "SHOOT", aim_location="CENTER", power=1.0),
                           gsK4, 0, 2, "MID", OverrideConfig())
assert tag == "counter" and out[0]["commandType"] == "PASS", (tag, out)
assert out[0]["parameters"]["target_player_id"] == 4, out
assert out[0]["parameters"]["type"] == "THROUGH", out

# K4b: FWD in opp half + effective range — SHOOT must survive (not counter).
gsK4b = copy.deepcopy(GAME_STATE)
gsK4b["ball"]["possessionAgentId"] = "agentId_4"
gsK4b["ball"]["position"] = {"x": 12.0, "y": 14.0, "z": 0}
for p in gsK4b["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_4":
        p["position"] = {"x": 12, "y": 14}
    elif p["teamCode"] == "away":
        p["position"] = {"x": 80, "y": 0}
out, tag = apply_overrides(_mk_for(4, "SHOOT", aim_location="CENTER", power=1.0),
                           gsK4b, 0, 4, "FWD2", OverrideConfig(longshot_max=58.0))
assert out[0]["commandType"] == "SHOOT", (tag, out)

# K5: phantom shot — no possession (opp holds in gs) but the LLM answers SHOOT.
# Non-designated P4 gets a real defensive job; designated P3 presses instead.
out, tag = apply_overrides(_mk_for(4, "SHOOT", aim_location="CENTER", power=1.0),
                           gs, 0, 4, "FWD2", OV)
assert tag == "phantom" and out[0]["commandType"] in ("MARK", "MOVE_TO"), (tag, out)
out, tag = apply_overrides(_mk_for(3, "SHOOT", aim_location="CENTER", power=1.0),
                           gs, 0, 3, "FWD1", OV)
assert tag == "phantom" and out[0]["commandType"] == "PRESS_BALL", (tag, out)

# --- Scenario M: iter-11 build-from-back (data-driven blast softening) ------
# Six matches of KPI history: far_shot_ratio 0.92-0.98, in_range_ticks = 0 —
# blind GK/DEF hoofs donated possession all game. Unpressured + clear lane
# now feeds the attack; pressured / no-outlet still blasts.
BUILD = OverrideConfig(always_blast=True, build_from_back=True)

gsM = copy.deepcopy(GAME_STATE)
gsM["ball"]["possessionAgentId"] = "agentId_0"
gsM["ball"]["position"] = {"x": -50.0, "y": 0.0, "z": 0}

# M1: GK safe open play -> long distribute (not blast).
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsM, 0, 0, "GK", BUILD)
assert tag in ("gk-dist", "gk-launch") and out[0]["commandType"] == "GK_DISTRIBUTE", (tag, out)

# M2: opponent parked on the GK -> blast, never a short throw/pass.
gsM2 = copy.deepcopy(gsM)
for p in gsM2["players"]:
    if p["teamCode"] == "away" and p["agentId"] == "agentId_1":
        p["position"] = {"x": -45, "y": 2}
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsM2, 0, 0, "GK", BUILD)
assert tag == "gk-blast" and out[0]["commandType"] == "SHOOT", (tag, out)

# M2b: crowded box + blocked lanes -> GK still blasts (skips route-one).
gsM2b = copy.deepcopy(gsM)
posM2b = {"agentId_1": (-45, 2), "agentId_2": (-15, 7.5),
          "agentId_3": (-18, -2.5), "agentId_4": (-22.5, -4)}
for p in gsM2b["players"]:
    if p["teamCode"] == "away" and p["agentId"] in posM2b:
        x, y = posM2b[p["agentId"]]
        p["position"] = {"x": x, "y": y}
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsM2b, 0, 0, "GK", BUILD)
assert tag == "gk-blast" and out[0]["commandType"] == "SHOOT", (tag, out)

# M3: GK with blockers but no pressure -> launch/distribute; blocked lanes -> clear.
gsM3 = copy.deepcopy(gsM)
blockers = {"agentId_2": (-15, 7.5), "agentId_3": (-18, -2.5), "agentId_4": (-22.5, -4)}
for p in gsM3["players"]:
    if p["teamCode"] == "away" and p["agentId"] in blockers:
        x, y = blockers[p["agentId"]]
        p["position"] = {"x": x, "y": y}
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsM3, 0, 0, "GK", BUILD)
assert tag in ("gk-dist", "gk-launch", "gk-clear", "gk-restart-clear") and (
    out[0]["commandType"] in ("GK_DISTRIBUTE", "SHOOT")), (tag, out)

# M4: always_blast on other positions does not force GK to hoof when safe.
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsM, 0, 0, "GK", BLAST)
assert tag in ("gk-dist", "gk-launch") and out[0]["commandType"] == "GK_DISTRIBUTE", (tag, out)

# M5: DEF builds too — holder at (-12,0), unpressured, lane to P4 open and
# short enough for a THROUGH ball.
gsM5 = copy.deepcopy(GAME_STATE)
gsM5["ball"]["possessionAgentId"] = "agentId_1"
gsM5["ball"]["position"] = {"x": -12.0, "y": 0.0, "z": 0}
for p in gsM5["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_1":
        p["position"] = {"x": -12, "y": 0}
out, tag = apply_overrides(_mk_for(1, "PASS", target_player_id=0, type="GROUND"),
                           gsM5, 0, 1, "DEF", BUILD)
assert tag == "build" and out[0]["commandType"] == "PASS", (tag, out)
assert out[0]["parameters"]["target_player_id"] == 4, out
assert out[0]["parameters"]["type"] == "THROUGH", out

# M6: unpressured GOAL_KICK -> long distribute (safe restart).
gsM6 = copy.deepcopy(gsM)
gsM6["playMode"] = "GOAL_KICK"
for p in gsM6["players"]:
    if p["teamCode"] == "away":
        p["position"] = {"x": 40, "y": p["position"].get("y", 0)}
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsM6, 0, 0, "GK", BUILD)
assert tag in ("gk-restart", "gk-launch", "gk-dist") and out[0]["commandType"] == "GK_DISTRIBUTE", (tag, out)

# M7: GOAL_KICK under press -> blast, never short distribute to feet.
gsM7 = copy.deepcopy(gsM6)
for p in gsM7["players"]:
    if p["teamCode"] == "away" and p["agentId"] == "agentId_1":
        p["position"] = {"x": -45, "y": 1}
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="KICK"),
                           gsM7, 0, 0, "GK", BUILD)
assert tag == "gk-blast" and out[0]["commandType"] == "SHOOT", (tag, out)

# M8: GOAL_KICK short throw under pressure -> blast, never gift at feet.
out, tag = apply_overrides(_mk_for(0, "GK_DISTRIBUTE", target_player_id=3, method="THROW"),
                           gsM7, 0, 0, "GK", BUILD)
assert tag == "gk-blast" and out[0]["commandType"] == "SHOOT", (tag, out)

# --- Scenario N: iter-11b attack support (FWD/MID must stretch, not mark) ---
# Tournament data (~4 matches): FWD1 0 shots, MID 2, 80-91% of attacker ticks
# were MOVE_TO+MARK. While a teammate holds the ball, attackers now either
# make an advancing run or get sent to the wide support spots.
# gs2: home P3 holds at (14,-5). FWD2 = P4 at (20,15), MID = P2 at (5,-8).

# N1: FWD2 marks during our possession -> wide penalty-spot support run (42, 9).
out, tag = apply_overrides(_mk_for(4, "MARK", target_player_id=1, tightness="TIGHT"),
                           gs2, 0, 4, "FWD2", OV)
assert tag == "support" and out[0]["commandType"] == "MOVE_TO", (tag, out)
assert out[0]["parameters"]["target_x"] == 42 and out[0]["parameters"]["target_y"] == 9.0, out

# N2: FWD2 drifts BACKWARDS (target_x 5 < current 20) -> support run.
out, tag = apply_overrides(_mk_for(4, "MOVE_TO", target_x=5, target_y=15, sprint=False),
                           gs2, 0, 4, "FWD2", OV)
assert tag == "support" and out[0]["parameters"]["target_x"] == 42, (tag, out)

# N3: FWD2 makes a genuinely advancing run (40 > 20+2) -> the LLM's own idea
# stands untouched.
out, tag = apply_overrides(_mk_for(4, "MOVE_TO", target_x=40, target_y=8, sprint=True),
                           gs2, 0, 4, "FWD2", OV)
assert tag is None and out[0]["parameters"]["target_x"] == 40, (tag, out)

# N4: MID parks in a stance -> pushed up to the edge-of-box support spot
# (x = 0.6 * 55 = 33, y follows the ball at 40%).
out, tag = apply_overrides(_mk_for(2, "SET_STANCE", stance=1),
                           gs2, 0, 2, "MID", OV)
assert tag == "support" and out[0]["commandType"] == "MOVE_TO", (tag, out)
assert out[0]["parameters"]["target_x"] == 33.0 and out[0]["parameters"]["target_y"] == -2.0, out

# N5: DEF may still MARK during our possession — the safety valve is exempt.
out, tag = apply_overrides(_mk_for(1, "MARK", target_player_id=1, tightness="TIGHT"),
                           gs2, 0, 1, "DEF", OV)
assert tag is None and out[0]["commandType"] == "MARK", (tag, out)

# --- Scenario O: iter-12 finishing + ball-winning package -------------------
# User report: carriers overran to the byline / dribbled and shot into packed
# boxes, defenders only ever marked, GK air-kicked loose balls in our box.

# O1: blocked in range -> SHOOT CENTER anyway (no open-lane carry loop).
gsO = copy.deepcopy(GAME_STATE)
gsO["ball"]["possessionAgentId"] = "agentId_3"
gsO["ball"]["position"] = {"x": 38.0, "y": 0.0, "z": 0}
posO_home = {"agentId_3": (38, 0), "agentId_4": (20, 15), "agentId_2": (5, -8)}
posO_away = {"agentId_1": (44, 0)}
for p in gsO["players"]:
    if p["teamCode"] == "home" and p["agentId"] in posO_home:
        x, y = posO_home[p["agentId"]]
        p["position"] = {"x": x, "y": y}
    elif p["teamCode"] == "away":
        x, y = posO_away.get(p["agentId"], (50, -30))
        p["position"] = {"x": x, "y": y}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=50, target_y=0, sprint=True),
                           gsO, 0, 3, "FWD1", OV)
assert tag == "shoot" and out[0]["commandType"] == "SHOOT", (tag, out)
assert out[0]["parameters"]["aim_location"] == "CENTER"

# O2: blocked lane but LLM chose SHOOT -> force CENTER anyway.
gsO2 = copy.deepcopy(gsO)
for p in gsO2["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_4":
        p["position"] = {"x": 10, "y": 20}
out, tag = apply_overrides(_mk("SHOOT", aim_location="CENTER", power=1.0),
                           gsO2, 0, 3, "FWD1", OV)
assert tag in ("shoot", "aim") and out[0]["commandType"] == "SHOOT", (tag, out)

# O2b: crowded ahead, LLM MOVE_TO in range -> still SHOOT.
gsO2b = copy.deepcopy(gsO)
for p in gsO2b["players"]:
    if p["teamCode"] == "away":
        p["position"] = {"x": 42, "y": 0}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=50, target_y=0, sprint=True),
                           gsO2b, 0, 3, "FWD1", OV)
assert tag == "shoot" and out[0]["commandType"] == "SHOOT", (tag, out)

# O3: out-of-range carry aimed at the byline (52) -> depth-capped at the box
# edge (44); a far target keeps the sprint, a near one drops it.
# Own-half carrier still out of snap-shot range at x=-10 (dist~66).
gsO3 = copy.deepcopy(GAME_STATE)
gsO3["ball"]["possessionAgentId"] = "agentId_3"
gsO3["ball"]["position"] = {"x": -10.0, "y": 14.0, "z": 0}
for p in gsO3["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": -10, "y": 14}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=52, target_y=14, sprint=True),
                           gsO3, 0, 3, "FWD1", OV)
assert tag == "cap" and out[0]["parameters"]["target_x"] == 44.0, (tag, out)
assert out[0]["parameters"]["sprint"] is True, out
gsO3b = copy.deepcopy(gsO3)
for p in gsO3b["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": 10, "y": 14}
    elif p["teamCode"] == "away":
        p["position"] = {"x": 80, "y": 0}
gsO3b["ball"]["position"] = {"x": 10.0, "y": 14.0, "z": 0}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=12, target_y=14, sprint=True),
                           gsO3b, 0, 3, "FWD1", OV)
assert tag in ("shoot", "snap-shot") and out[0]["commandType"] == "SHOOT", (tag, out)
assert out[0]["parameters"]["aim_location"] == "CENTER", out
# In range from own half — forced shot fires without needing opp-half entry.
gsO3c = copy.deepcopy(GAME_STATE)
gsO3c["ball"]["possessionAgentId"] = "agentId_3"
gsO3c["ball"]["position"] = {"x": 0.0, "y": 0.0, "z": 0}
for p in gsO3c["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": 0, "y": 0}
    elif p["teamCode"] == "away":
        p["position"] = {"x": 80, "y": 0}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=30, target_y=0, sprint=True),
                           gsO3c, 0, 3, "FWD1", OverrideConfig(longshot_max=58.0))
assert tag in ("shoot", "snap-shot") and out[0]["commandType"] == "SHOOT", (tag, out)

# O4: designated presser 2.2 from the carrier -> the shadowing becomes a slide.
gsO4 = copy.deepcopy(gs)  # away P3 holds at (30,-12)
for p in gsO4["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": 28, "y": -11}
out, tag = apply_overrides(_mk("PRESS_BALL", intensity=1.0), gsO4, 0, 3, "FWD1", OV)
assert tag == "tackle" and out[0]["commandType"] == "SLIDE_TACKLE", (tag, out)
assert out[0]["parameters"]["target_player_id"] == -1, out

# O5: FWD designated on loose ball but far upfield -> mark duty, not deep INTERCEPT.
gsO5 = copy.deepcopy(GAME_STATE)
gsO5["ball"]["possessionAgentId"] = None
gsO5["ball"]["isFree"] = True
out, tag = apply_overrides(_mk("MOVE_TO", target_x=15, target_y=-5, sprint=True),
                           gsO5, 0, 3, "FWD1", OV)
assert tag == "no-chase" and out[0]["commandType"] == "MARK", (tag, out)

# O5b: MID designated on loose ball in our half -> INTERCEPT.
gsO5b = copy.deepcopy(GAME_STATE)
gsO5b["ball"]["possessionAgentId"] = None
gsO5b["ball"]["isFree"] = True
gsO5b["ball"]["position"] = {"x": -47.0, "y": 2.0, "z": 0}
for p in gsO5b["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_2":
        p["position"] = {"x": -44, "y": 1}
out, tag = apply_overrides(_mk("MOVE_TO", target_x=-46, target_y=2, sprint=True),
                           gsO5b, 0, 2, "MID", OV)
assert tag == "intercept" and out[0]["commandType"] == "INTERCEPT", (tag, out)

# O6: GK phantom SHOOT with a loose ball 2.8 away -> smother it (INTERCEPT).
gsO6 = copy.deepcopy(GAME_STATE)
gsO6["ball"]["possessionAgentId"] = None
gsO6["ball"]["isFree"] = True
gsO6["ball"]["position"] = {"x": -48.0, "y": 2.0, "z": 0}
out, tag = apply_overrides(_mk_for(0, "SHOOT", aim_location="CENTER", power=1.0),
                           gsO6, 0, 0, "GK", BLAST)
assert tag == "gk-smother" and out[0]["commandType"] == "INTERCEPT", (tag, out)

# O7: GK sweeper MOVE_TO while opponent carries upfield -> forced back to the line.
out, tag = apply_overrides(_mk_for(0, "SHOOT", aim_location="CENTER", power=1.0),
                           gs, 0, 0, "GK", BLAST)
assert tag in ("gk-cover", "gk-line") and out[0]["commandType"] == "MOVE_TO", (tag, out)
assert out[0]["parameters"]["target_x"] == -52.8, out
assert out[0]["parameters"]["target_y"] == -6.0, out
assert out[0]["parameters"]["sprint"] is False, out

# O7b: GK LLM MOVE_TO x≈-6 (sweeper) -> clamped to goal line every tick.
out, tag = apply_overrides(_mk_for(0, "MOVE_TO", target_x=-6, target_y=0, sprint=True),
                           gs, 0, 0, "GK", BLAST)
assert tag == "gk-line" and out[0]["parameters"]["target_x"] == -52.8, (tag, out)

# O8: build-from-back DEF, unpressed but every outlet lane has a body on it ->
# iter-13: launch AERIAL to P4 in the opp half before wing carry.
gsO8 = copy.deepcopy(GAME_STATE)
gsO8["ball"]["possessionAgentId"] = "agentId_1"
gsO8["ball"]["position"] = {"x": -12.0, "y": 0.0, "z": 0}
posO8_away = {"agentId_1": (-1, -4), "agentId_2": (1, -2), "agentId_3": (4, 7)}
for p in gsO8["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_1":
        p["position"] = {"x": -12, "y": 0}
    elif p["teamCode"] == "away" and p["agentId"] in posO8_away:
        x, y = posO8_away[p["agentId"]]
        p["position"] = {"x": x, "y": y}
out, tag = apply_overrides(_mk_for(1, "PASS", target_player_id=0, type="GROUND"),
                           gsO8, 0, 1, "DEF", BUILD)
assert tag == "launch" and out[0]["commandType"] == "PASS", (tag, out)
assert out[0]["parameters"]["target_player_id"] == 4, out
assert out[0]["parameters"]["type"] == "AERIAL", out

# O9 (iter-12b): DEF PRESSED (opponent 3 from the ball) with every ground lane
# shut -> route-one AERIAL to the most advanced forward, never a blind blast.
# gsM2b already has a body on the GK and blockers on all outlet lanes; put a
# presser right on the deep DEF and confirm the launch beats the blast.
gsO9 = copy.deepcopy(GAME_STATE)
gsO9["ball"]["possessionAgentId"] = "agentId_1"
gsO9["ball"]["position"] = {"x": -30.0, "y": 0.0, "z": 0}
posO9_home = {"agentId_1": (-30, 0), "agentId_2": (-20, 6),
              "agentId_3": (12, -10), "agentId_4": (18, 12)}
posO9_away = {"agentId_1": (-28, 1), "agentId_2": (-18, 6),
              "agentId_3": (10, -9), "agentId_4": (16, 12)}
for p in gsO9["players"]:
    if p["teamCode"] == "home" and p["agentId"] in posO9_home:
        x, y = posO9_home[p["agentId"]]
        p["position"] = {"x": x, "y": y}
    elif p["teamCode"] == "away" and p["agentId"] in posO9_away:
        x, y = posO9_away[p["agentId"]]
        p["position"] = {"x": x, "y": y}
out, tag = apply_overrides(_mk_for(1, "PASS", target_player_id=0, type="GROUND"),
                           gsO9, 0, 1, "DEF", BUILD)
assert tag == "launch" and out[0]["commandType"] == "PASS", (tag, out)
assert out[0]["parameters"]["target_player_id"] == 4, out  # most advanced FWD
assert out[0]["parameters"]["type"] == "AERIAL", out

# O9b: same trap but NO forward is upfield of the presser -> only then blast.
gsO9b = copy.deepcopy(gsO9)
for p in gsO9b["players"]:
    if p["teamCode"] == "home" and p["agentId"] in ("agentId_2", "agentId_3", "agentId_4"):
        p["position"] = {"x": -34, "y": p["position"]["y"]}  # everyone behind the ball
out, tag = apply_overrides(_mk_for(1, "PASS", target_player_id=0, type="GROUND"),
                           gsO9b, 0, 1, "DEF", BUILD)
assert tag in ("blast", "gk-clear", "gk-blast") and out[0]["commandType"] == "SHOOT", (tag, out)

# --- Scenario L: tuning overlay (autopilot control surface) -----------------
from tuning import apply_tuning, clamp, get as tuning_get

base_cfg = OverrideConfig()
# global + position overlay, position wins; out-of-bounds values are clamped
tunedL = apply_tuning(base_cfg, "MID", {
    "global": {"shoot_threshold": 47.0, "press_bodies": 2},
    "MID": {"shoot_threshold": 99.0},          # above BOUNDS max -> clamped to 50
})
assert tunedL.shoot_threshold == 50.0, tunedL.shoot_threshold
assert tunedL.press_bodies == 2 and isinstance(tunedL.press_bodies, int), tunedL
assert base_cfg.shoot_threshold == 45.0, "original config must not mutate"
# unknown keys are ignored; empty tuning returns the same object; None passes
tunedL2 = apply_tuning(base_cfg, "GK", {"global": {"not_a_field": 1}})
assert tunedL2.shoot_threshold == base_cfg.shoot_threshold
assert apply_tuning(base_cfg, "DEF", {}) is base_cfg
assert apply_tuning(None, "DEF", {"global": {"press_bodies": 2}}) is None
assert clamp("press_bodies", 10) == 4 and clamp("gk_out_dist", 1.0) == 8.0
assert tuning_get("longshot_max", 52.0, {"global": {"longshot_max": 100}}) == 58.0
# booleans ride through tuning.json untouched; their numeric knobs clamp
tunedM = apply_tuning(OverrideConfig(always_blast=True), "GK",
                      {"global": {"build_from_back": True, "blast_pressure_dist": 99}})
assert tunedM.build_from_back is True, tunedM
assert tunedM.blast_pressure_dist == 16.0, tunedM.blast_pressure_dist

print("Scenario A (away P3 holds): home view OPP / away view MY — OK")
print("Scenario B (home P3 holds): hasBall=True + SHOOT NOW CENTER 1.0 — OK")
print("Scenario C (opp GK holds): our GK hasBall=False — OK")
print("Scenario D (coach/free-ball/stamina/lastAction enrichment) — OK")
print("Scenario E (chase/press assignments, one player to the ball) — OK")
print("Scenario F (late-game GAME PLAN by score) — OK")
print("Scenario G (command guardrails clamp bad params) — OK")
print("Scenario H (LANE CLEAR / BLOCKED shot check with sidestep hint) — OK")
print("Scenario I (point-blank always shoots even with slight overlap) — OK")
print("Scenario J (tactical overrides: forced shot / no-chase / anchor / support) — OK")
print("Scenario K (GK/DEF blast, long shot, counter outlet, phantom fix) — OK")
print("Scenario M (build-from-back: outlet when safe, blast when pressed) — OK")
print("Scenario N (attack support: FWD/MID stretch wide instead of marking) — OK")
print("Scenario O (cutback/sidestep/carry-cap/tackle/intercept/GK smother) — OK")
print("Scenario L (tuning.json overlay: merge, clamp, immutability) — OK")
# --- Scenario Q: fallback shoot-first when LLM would have failed ------------
from fallback import build_fallback, FWD1_CONFIG
fb = build_fallback(FWD1_CONFIG)
gsQ = copy.deepcopy(GAME_STATE)
gsQ["ball"]["possessionAgentId"] = "agentId_3"
gsQ["ball"]["position"] = {"x": 7.0, "y": -14.0, "z": 0}
for p in gsQ["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_3":
        p["position"] = {"x": 7, "y": -14}
    elif p["teamCode"] == "away":
        p["position"] = {"x": 80, "y": 0}  # clear lanes so geometry aim is deterministic
outQ = fb(gsQ, 0, 3)
assert outQ[0]["commandType"] == "SHOOT", outQ
assert outQ[0]["parameters"]["aim_location"] == "CENTER"
assert outQ[0]["parameters"]["power"] >= 0.95, outQ

from tactics import _best_shot_aim, _aim_geometry_line
aim_open, _, perp_open = _best_shot_aim({"x": 30, "y": -14}, 55, [])
assert aim_open == "CENTER" and perp_open > 0, aim_open
blocked, _, perp_blk = _best_shot_aim({"x": 30, "y": -14}, 55,
    [{"position": {"x": 52, "y": 0}}])
assert blocked == "CENTER" and perp_blk < 2.5, (blocked, perp_blk)
assert "open space" in _aim_geometry_line({"x": 30, "y": -14}, 55, "CENTER")

print("Scenario P (carry open then SHOOT CENTER) — OK")
print("Scenario Q (fallback: long-range wing -> geometry SHOOT) — OK")

# --- Scenario R: compact defense — near opponent marks, helper press on carrier ---
gsR = copy.deepcopy(gs)  # away P3 holds at (30,-12)
# P2 is designated presser (closest to ball); P4 shadows a nearby opponent
for p in gsR["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_2":
        p["position"] = {"x": 25, "y": -11}
    if p["teamCode"] == "home" and p["agentId"] == "agentId_4":
        p["position"] = {"x": 18, "y": -5}
    if p["teamCode"] == "away" and p["agentId"] == "agentId_1":
        p["position"] = {"x": 25, "y": -8}
outR, tagR = apply_overrides(
    [{"commandType": "MOVE_TO", "playerId": 4, "teamId": 0,
      "parameters": {"target_x": 40, "target_y": 15, "sprint": True}}],
    gsR, 0, 4, "FWD2", OverrideConfig(mark_radius=28.0))
assert tagR in ("mark-near", "anchor", "no-chase"), (tagR, outR)
assert outR[0]["commandType"] == "MARK", (tagR, outR)
assert outR[0]["parameters"]["tightness"] == "TIGHT", outR

# P4 within press_radius of carrier but P2 remains designated presser
for p in gsR["players"]:
    if p["teamCode"] == "home" and p["agentId"] == "agentId_2":
        p["position"] = {"x": 29, "y": -12}
    if p["teamCode"] == "home" and p["agentId"] == "agentId_4":
        p["position"] = {"x": 28, "y": -10}
outR2, tagR2 = apply_overrides(
    [{"commandType": "MOVE_TO", "playerId": 4, "teamId": 0,
      "parameters": {"target_x": 0, "target_y": 0, "sprint": False}}],
    gsR, 0, 4, "FWD2", OverrideConfig(press_radius=20.0))
assert tagR2 in ("mark-near", "no-chase", "anchor"), (tagR2, outR2)
assert outR2[0]["commandType"] in ("MARK", "PRESS_BALL", "SLIDE_TACKLE"), (tagR2, outR2)

# --- Scenario S: back line — DEF/MID hold depth when ball is in opponent half ---
# gs: away P3 holds at (30,-12). DEF must not MARK or chase to x≈-6.
outS, tagS = apply_overrides(_mk_for(1, "MARK", target_player_id=1, tightness="TIGHT"),
                             gs, 0, 1, "DEF", OV)
assert tagS in ("hold-line", "anchor") and outS[0]["commandType"] == "MOVE_TO", (tagS, outS)
assert -43 <= outS[0]["parameters"]["target_x"] <= -27, outS

outS2, tagS2 = apply_overrides(_mk_for(2, "MARK", target_player_id=1, tightness="TIGHT"),
                               gs, 0, 2, "MID", OV)
assert tagS2 in ("hold-line", "anchor") and outS2[0]["commandType"] == "MOVE_TO", (tagS2, outS2)
assert -33 <= outS2[0]["parameters"]["target_x"] <= -17, outS2

print("Scenario R (compact defense: mark near / press carrier) — OK")
# --- Scenario T: defensive phase — never sprint to opponent baseline on chase ---
gsT = copy.deepcopy(GAME_STATE)
gsT["ball"]["possessionAgentId"] = None
gsT["ball"]["isFree"] = True
gsT["ball"]["position"] = {"x": 25.0, "y": -5.0, "z": 0}
outT, tagT = apply_overrides(_mk("MOVE_TO", target_x=45, target_y=10, sprint=True),
                             gsT, 0, 2, "MID", OV)
assert tagT in ("no-chase", "anchor", "hold-line", "mark-near") and outT[0]["commandType"] == "MOVE_TO", (tagT, outT)
assert outT[0]["parameters"]["target_x"] <= -17, outT

print("Scenario S (back line: DEF/MID hold depth, no x≈-6 collapse) — OK")
print("Scenario T (no baseline chase on loose ball in opponent half) — OK")
print("ALL LIB TESTS PASSED")
