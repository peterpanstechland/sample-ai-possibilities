"""Post-LLM tactical overrides — prompts suggest, code enforces.

Match evidence (aggressive team vs bot): 207/370 commands were MOVE_TO, 101
PRESS_BALL, 0 MARK — despite prompts ordering "MARK when a teammate presses".
The LLM answered 100% of ticks (fallback never ran), so every rule that lived
only in the prompt or the fallback was effectively optional. This module makes
the match-deciding rules deterministic:

  1. blast — GK/DEF possession is ALWAYS an instant full-power shot at the
     clearest part of the goal frame: clearance + shot in one, no range limit
     (skipped on set-piece play modes so restarts keep their mechanics);
     with build_from_back (iter-11), an UNPRESSURED GK/DEF with a clear lane
     to an advanced teammate plays the outlet pass instead — six matches of
     KPI history showed 92-98% of our shots were 45+ hoofs and the team never
     held the ball inside shooting range, so blind blasts just fed the
     opponent's attack;
  2. shot enforcement — MID/FWD holding in range with a clear lane ALWAYS
     shoot (an LLM shot at a covered corner is re-aimed at the open one);
  3. long shot — 45-52 out with the opponent GK off his line and a clear
     lane: shoot the open frame (the only long shot worth taking);
  4. counter — deep possession under a high press (3+ opponents in our half)
     or a panic blast from out of range becomes ONE fast THROUGH pass to the
     most advanced open forward; no outlet -> carry up the wing;
  5. phantom — SHOOT/PASS without the ball wastes the tick; designated player
     presses instead, everyone else takes a real defensive job;
  6. no-chase — a non-designated player pressing/chasing is rewritten to a
     MARK on the nearest passing option or a compact-line position;
  7. anchor clamp — defensive-phase MOVE_TO far off the role's ball-shifted
     compact line becomes a real defensive job (line drops deeper when the
     opponent commits bodies forward).

Only teams that pass an OverrideConfig into create_invoke_handler get this
behaviour — other teams' pipelines are byte-for-byte unchanged.
"""

from __future__ import annotations
from dataclasses import dataclass

from state import (get_goal_positions, dist, _player_idx, _is_my_team,
                   resolve_holder, count_opponents_in_our_half)
from tactics import _best_shot_aim

_CHASE_CMDS = ("PRESS_BALL", "INTERCEPT", "SLIDE_TACKLE")
_NEEDS_BALL_CMDS = ("PASS", "SHOOT", "GK_DISTRIBUTE")
_SET_PIECE_MODES = {"GOALKICK", "FREEKICK", "KICKOFF", "CORNER", "CORNERKICK",
                    "THROWIN", "PENALTY"}


def _is_set_piece(play_mode) -> bool:
    pm = str(play_mode or "").upper().replace("_", "").replace(" ", "")
    return pm in _SET_PIECE_MODES


@dataclass
class OverrideConfig:
    enforce_shot: bool = True
    shoot_threshold: float = 45.0
    always_blast: bool = False
    """GK/DEF: ANY open-play possession -> full-power shot at the clearest aim.
    Doubles as a clearance; no distance limit by design."""
    build_from_back: bool = False
    """Softens always_blast (iter-11, from match data): unpressured possession
    with a clear advancing lane becomes an outlet pass that feeds the attack;
    the blast remains the pressured / no-outlet fallback."""
    blast_pressure_dist: float = 10.0
    """An opponent within this of the carrier counts as pressure -> blast."""
    counter_attack: bool = True
    longshot_max: float = 52.0
    gk_out_dist: float = 12.0
    """Opponent GK this far off his goal center counts as 'off his line'."""
    outlet_min_gain: float = 12.0
    """Outlet must be at least this much closer to the opponent goal than me."""
    outlet_lane_radius: float = 5.0
    press_bodies: int = 3
    """Opponents in our half that constitute a HIGH PRESS (counter trigger)."""
    no_chase: bool = True
    chase_radius: float = 8.0
    """MOVE_TO with a target this close to the ball counts as chasing it."""
    compact_anchor: bool = True
    anchor_slack: float = 12.0
    """Defensive MOVE_TO targets further than this from the anchor get clamped."""
    mark_radius: float = 22.0
    """MARK the nearest opponent if within this range, else hold the anchor."""
    wing_y: float = 0.0
    """Forwards only: carrying the ball out of range down the center (|y|<8)
    is steered to this wing lane. 0 disables."""


def _cmd(cmd_type: str, pid: int, tid: int, params: dict, duration: int = 0) -> dict:
    return {"commandType": cmd_type, "playerId": pid, "teamId": tid,
            "parameters": params, "duration": duration}


def _between(a: float, b: float, v: float) -> float:
    lo, hi = (a, b) if a <= b else (b, a)
    return max(lo, min(hi, v))


def _anchor(position_label: str, team_id: int, ball_pos: dict,
            deep: bool = False) -> tuple[float, float]:
    """Role anchor on a compact, ball-shifted line. dir_my points at my goal,
    so `bx + k*dir_my` is k units goal-side of the ball for either team.
    Under a high press (deep=True) DEF/MID drop closer to goal while the
    forwards' floor RISES — they stay high as the counter-attack outlets."""
    my_goal_x, _ = get_goal_positions(team_id)
    dir_my = 1.0 if my_goal_x > 0 else -1.0
    bx, by = ball_pos.get("x", 0), ball_pos.get("y", 0)
    if position_label == "DEF":
        k, hi = (14, 2 * dir_my) if deep else (12, 6 * dir_my)
        return (_between(0.85 * my_goal_x, hi, bx + k * dir_my),
                _between(-12.0, 12.0, by * 0.5))
    if position_label == "MID":
        k, hi = (7, -4 * dir_my) if deep else (5, -8 * dir_my)
        return (_between(0.7 * my_goal_x, hi, bx + k * dir_my),
                _between(-14.0, 14.0, by * 0.6))
    # Forwards: stay high for the counter but pinch toward the middle
    wing = -10.0 if position_label == "FWD1" else 10.0
    lo = 6 * dir_my if deep else 12 * dir_my
    return (_between(lo, -25 * dir_my, bx - 12 * dir_my), wing)


def _support_spot(position_label: str, team_id: int, ball_pos: dict) -> tuple[float, float]:
    """Where to run when a teammate has the ball (attack support)."""
    my_goal_x, opp_goal_x = get_goal_positions(team_id)
    dir_my = 1.0 if my_goal_x > 0 else -1.0
    if position_label == "FWD1":
        return opp_goal_x + 7 * dir_my, -6.0
    if position_label == "FWD2":
        return opp_goal_x + 7 * dir_my, 6.0
    if position_label == "MID":
        return opp_goal_x * 0.6, _between(-10.0, 10.0, ball_pos.get("y", 0) * 0.4)
    return -8 * dir_my, 0.0  # DEF: sit just past halfway as the safety valve


def _pass_lane_clear(me_pos, tgt_pos, opponents, radius: float) -> bool:
    """No opponent within `radius` of the pass segment (ignoring bodies right
    next to the passer, t<0.15 — the ball leaves too fast there)."""
    dx = tgt_pos.get("x", 0) - me_pos.get("x", 0)
    dy = tgt_pos.get("y", 0) - me_pos.get("y", 0)
    l2 = dx * dx + dy * dy
    if l2 < 1:
        return True
    for o in opponents:
        p = o.get("position", {}) or {}
        rx = p.get("x", 0) - me_pos.get("x", 0)
        ry = p.get("y", 0) - me_pos.get("y", 0)
        t = (rx * dx + ry * dy) / l2
        if t < 0.15:
            continue
        t = min(1.0, t)
        cx, cy = me_pos.get("x", 0) + t * dx, me_pos.get("y", 0) + t * dy
        if dist({"x": cx, "y": cy}, p) < radius:
            return False
    return True


def _best_outlet(cfg, players, team_id, my_player_id, me_pos, opp_goal_x,
                 opponents):
    """Most advanced teammate (MID/FWDs) meaningfully closer to goal with a
    clear pass lane. Returns player idx or None."""
    goal = {"x": opp_goal_x, "y": 0}
    my_d = dist(me_pos, goal)
    best_idx, best_d = None, None
    for p in players:
        idx = _player_idx(p)
        if not _is_my_team(p, team_id) or idx == my_player_id or idx not in (2, 3, 4):
            continue
        pos = p.get("position", {}) or {}
        d = dist(pos, goal)
        if my_d - d < cfg.outlet_min_gain:
            continue
        if not _pass_lane_clear(me_pos, pos, opponents, cfg.outlet_lane_radius):
            continue
        if best_d is None or d < best_d:
            best_idx, best_d = idx, d
    return best_idx


def _defensive_duty(cfg, position_label, team_id, my_player_id, me_pos,
                    ball_pos, opponents, holder=None, deep=False) -> dict:
    """MARK the nearest opponent outfielder, else hold the compact anchor.
    The ball carrier is excluded — the designated presser handles them, the
    rest of the team takes away the passing options."""
    ax, ay = _anchor(position_label, team_id, ball_pos, deep)
    markable = [o for o in opponents if _player_idx(o) != 0 and o is not holder]
    if markable:
        target = min(markable, key=lambda o: dist(o.get("position", {}) or {}, me_pos))
        if dist(target.get("position", {}) or {}, me_pos) <= cfg.mark_radius:
            return _cmd("MARK", my_player_id, team_id,
                        {"target_player_id": _player_idx(target),
                         "tightness": "TIGHT"}, duration=3)
    sprint = dist(me_pos, {"x": ax, "y": ay}) > 12
    return _cmd("MOVE_TO", my_player_id, team_id,
                {"target_x": round(ax, 1), "target_y": round(ay, 1), "sprint": sprint})


def _force_shot(commands, cmd, ctype, params, my_player_id, team_id,
                aim: str, tag: str):
    """Rewrite/patch the command into a full-power shot at `aim`.
    Tag is only reported when something actually changed."""
    if ctype != "SHOOT":
        return [_cmd("SHOOT", my_player_id, team_id,
                     {"aim_location": aim, "power": 1.0})], tag
    changed = params.get("power") != 1.0 or params.get("aim_location") != aim
    params["power"] = 1.0
    params["aim_location"] = aim
    return commands, (tag if changed else None)


def apply_overrides(commands: list[dict], game_state: dict, team_id: int,
                    my_player_id: int, position_label: str,
                    cfg: OverrideConfig | None) -> tuple[list[dict], str | None]:
    """Rewrite the LLM's first command when it violates a hard tactical rule.
    Returns (commands, override_tag) — tag is None when nothing was changed."""
    if cfg is None or not commands:
        return commands, None

    ball = game_state.get("ball", {}) or {}
    ball_pos = ball.get("position", {}) or {}
    players = game_state.get("players", []) or []
    me = next((p for p in players
               if _player_idx(p) == my_player_id and _is_my_team(p, team_id)), None)
    if me is None:
        return commands, None
    me_pos = me.get("position", {}) or {}

    my_goal_x, opp_goal_x = get_goal_positions(team_id)
    dir_my = 1.0 if my_goal_x > 0 else -1.0
    holder = resolve_holder(ball, players)
    i_have = holder is me
    teammate_has = holder is not None and holder is not me and _is_my_team(holder, team_id)
    opp_has = holder is not None and not _is_my_team(holder, team_id)
    opponents = [p for p in players if not _is_my_team(p, team_id)]

    cmd = commands[0]
    ctype = cmd.get("commandType")
    params = cmd.get("parameters") or {}
    cmd["parameters"] = params

    # --- 0. GK/DEF blast: any open-play possession is an instant shot -------
    # Set pieces keep their restart mechanics (GK_DISTRIBUTE on goal kicks etc).
    if cfg.always_blast and i_have and not _is_set_piece(game_state.get("playMode")):
        if cfg.build_from_back and opponents:
            # Match data (iters 6-10): ~95% of team shots were 45+ blasts and
            # we never held the ball inside range — every hoof donated the
            # ball straight back. When NOBODY is pressing and a clean lane to
            # an advanced teammate exists, feed the attack instead.
            pressed = min(dist(o.get("position", {}) or {}, me_pos)
                          for o in opponents) <= cfg.blast_pressure_dist
            if not pressed:
                outlet = _best_outlet(cfg, players, team_id, my_player_id,
                                      me_pos, opp_goal_x, opponents)
                if outlet is not None:
                    tgt = next(p for p in players
                               if _player_idx(p) == outlet and _is_my_team(p, team_id))
                    long_ball = dist(me_pos, tgt.get("position", {}) or {}) > 45
                    return [_cmd("PASS", my_player_id, team_id,
                                 {"target_player_id": outlet,
                                  "type": "AERIAL" if long_ball else "THROUGH"})], "build"
        aim, _, _ = _best_shot_aim(me_pos, opp_goal_x, opponents)
        return _force_shot(commands, cmd, ctype, params, my_player_id, team_id,
                           aim, "blast")

    if my_player_id == 0:
        return commands, None  # GK: nothing below applies (guards its box)

    # --- 1. I hold the ball (MID / FWDs) -------------------------------------
    if i_have:
        d_goal = dist(me_pos, {"x": opp_goal_x, "y": 0})
        lane_radius = 1.5 if d_goal <= 25 else 2.5
        aim, _, perp = _best_shot_aim(me_pos, opp_goal_x, opponents)
        lane_clear = perp >= lane_radius

        if cfg.enforce_shot and d_goal <= cfg.shoot_threshold:
            point_blank = d_goal <= 15
            if lane_clear or point_blank:
                desired = aim if lane_clear else "CENTER"
                return _force_shot(commands, cmd, ctype, params, my_player_id,
                                   team_id, desired, "shoot" if ctype != "SHOOT" else "aim")
            return commands, None  # blocked in range: LLM may sidestep/pass

        # Out of range from here on.
        opp_gk = next((o for o in opponents if _player_idx(o) == 0), None)
        gk_out = (opp_gk is not None
                  and dist(opp_gk.get("position", {}) or {},
                           {"x": opp_goal_x, "y": 0}) >= cfg.gk_out_dist)
        if (cfg.counter_attack and d_goal <= cfg.longshot_max
                and gk_out and lane_clear):
            # Their keeper joined the push — lob the open frame.
            return _force_shot(commands, cmd, ctype, params, my_player_id,
                               team_id, aim, "longshot")

        if cfg.counter_attack:
            pressure = count_opponents_in_our_half(game_state, team_id)
            panic_blast = ctype == "SHOOT"
            pressed_carry = pressure >= cfg.press_bodies and ctype == "MOVE_TO"
            if panic_blast or pressed_carry:
                outlet = _best_outlet(cfg, players, team_id, my_player_id,
                                      me_pos, opp_goal_x, opponents)
                if outlet is not None:
                    return [_cmd("PASS", my_player_id, team_id,
                                 {"target_player_id": outlet,
                                  "type": "THROUGH"})], "counter"
                if panic_blast:
                    # No outlet: carry up the wing instead of donating the ball
                    ty = cfg.wing_y or (10.0 if me_pos.get("y", 0) >= 0 else -10.0)
                    tx = me_pos.get("x", 0) - 12 * dir_my
                    return [_cmd("MOVE_TO", my_player_id, team_id,
                                 {"target_x": round(tx, 1), "target_y": ty,
                                  "sprint": True})], "counter"

        # Carrying out of range down the middle -> steer to the wing lane
        if cfg.wing_y and ctype == "MOVE_TO":
            ty = params.get("target_y")
            tx = params.get("target_x")
            toward_opp = isinstance(tx, (int, float)) and (tx - me_pos.get("x", 0)) * -dir_my > 0
            if isinstance(ty, (int, float)) and abs(ty) < 8 and toward_opp:
                params["target_y"] = cfg.wing_y
                return commands, "wing"
        return commands, None

    # --- 2. Teammate holds it: commands that need the ball become support runs
    if teammate_has:
        if ctype in _NEEDS_BALL_CMDS or ctype in _CHASE_CMDS:
            sx, sy = _support_spot(position_label, team_id, ball_pos)
            return [_cmd("MOVE_TO", my_player_id, team_id,
                         {"target_x": round(sx, 1), "target_y": round(sy, 1),
                          "sprint": True})], "support"
        return commands, None

    # --- 3. Defensive phase: opponent possession or free ball ---------------
    my_team = [p for p in players if _is_my_team(p, team_id)]
    closest = min(my_team, key=lambda p: dist(p.get("position", {}) or {}, ball_pos),
                  default=None)
    designated = closest is not None and _player_idx(closest) == my_player_id
    pressure = count_opponents_in_our_half(game_state, team_id)
    deep = pressure >= cfg.press_bodies
    ball_in_our_half = ball_pos.get("x", 0) * dir_my > 0

    # Phantom ball actions (SHOOT/PASS with no possession) waste the tick.
    if ctype in _NEEDS_BALL_CMDS:
        if designated:
            return [_cmd("PRESS_BALL", my_player_id, team_id,
                         {"intensity": 1.0}, duration=3)], "phantom"
        return [_defensive_duty(cfg, position_label, team_id, my_player_id,
                                me_pos, ball_pos, opponents, holder, deep)], "phantom"

    if designated:
        return commands, None  # the designated player may chase/press freely

    chasing = ctype in _CHASE_CMDS
    if not chasing and ctype == "MOVE_TO":
        tx, ty = params.get("target_x"), params.get("target_y")
        if isinstance(tx, (int, float)) and isinstance(ty, (int, float)):
            chasing = dist({"x": tx, "y": ty}, ball_pos) < cfg.chase_radius

    if cfg.no_chase and chasing:
        if opp_has or ball_in_our_half:
            return [_defensive_duty(cfg, position_label, team_id, my_player_id,
                                    me_pos, ball_pos, opponents, holder, deep)], "no-chase"
        sx, sy = _support_spot(position_label, team_id, ball_pos)
        return [_cmd("MOVE_TO", my_player_id, team_id,
                     {"target_x": round(sx, 1), "target_y": round(sy, 1),
                      "sprint": True})], "no-chase"

    if cfg.compact_anchor and ctype == "MOVE_TO" and (opp_has or ball_in_our_half):
        ax, ay = _anchor(position_label, team_id, ball_pos, deep)
        tx, ty = params.get("target_x"), params.get("target_y")
        bad_target = not (isinstance(tx, (int, float)) and isinstance(ty, (int, float)))
        if bad_target or dist({"x": tx, "y": ty}, {"x": ax, "y": ay}) > cfg.anchor_slack:
            # A wandering defensive MOVE_TO becomes a real defensive job:
            # tight-mark the nearest passing option, or hold the compact line.
            return [_defensive_duty(cfg, position_label, team_id, my_player_id,
                                    me_pos, ball_pos, opponents, holder, deep)], "anchor"

    return commands, None
