"""Post-LLM tactical overrides — prompts suggest, code enforces.

Match evidence (aggressive team vs bot): 207/370 commands were MOVE_TO, 101
PRESS_BALL, 0 MARK — despite prompts ordering "MARK when a teammate presses".
The LLM answered 100% of ticks (fallback never ran), so every rule that lived
only in the prompt or the fallback was effectively optional. This module makes
the three rules that decide matches deterministic:

  1. shot enforcement — holder in range with a clear lane ALWAYS shoots
     (and an LLM shot at a covered corner is re-aimed at the open one);
  2. no-chase — a non-designated player pressing/chasing is rewritten to a
     MARK on the nearest opponent or a compact-line position;
  3. anchor clamp — defensive-phase MOVE_TO far away from the role's anchor
     (a ball-shifted compact line) is pulled back to the anchor.

Plus two small pathology fixes: forwards carrying the ball down the middle are
steered to their wing, and PASS/PRESS/SHOOT without the ball while a teammate
holds it becomes a support run. GK (player 0) is exempt from everything.

Only teams that pass an OverrideConfig into create_invoke_handler get this
behaviour — other teams' pipelines are byte-for-byte unchanged.
"""

from __future__ import annotations
from dataclasses import dataclass

from state import (get_goal_positions, dist, _player_idx, _is_my_team,
                   resolve_holder)
from tactics import _best_shot_aim

_AIM_Y = {"CENTER": 0.0, "TL": -4.0, "TR": 4.0, "BL": -4.0, "BR": 4.0}
_CHASE_CMDS = ("PRESS_BALL", "INTERCEPT", "SLIDE_TACKLE")
_NEEDS_BALL_CMDS = ("PASS", "SHOOT", "GK_DISTRIBUTE", "PRESS_BALL",
                    "INTERCEPT", "SLIDE_TACKLE")


@dataclass
class OverrideConfig:
    enforce_shot: bool = True
    shoot_threshold: float = 45.0
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


def _anchor(position_label: str, team_id: int, ball_pos: dict) -> tuple[float, float]:
    """Role anchor on a compact, ball-shifted line. dir_my points at my goal,
    so `bx + k*dir_my` is k units goal-side of the ball for either team."""
    my_goal_x, _ = get_goal_positions(team_id)
    dir_my = 1.0 if my_goal_x > 0 else -1.0
    bx, by = ball_pos.get("x", 0), ball_pos.get("y", 0)
    if position_label == "DEF":
        return (_between(0.82 * my_goal_x, 6 * dir_my, bx + 12 * dir_my),
                _between(-12.0, 12.0, by * 0.5))
    if position_label == "MID":
        return (_between(0.7 * my_goal_x, -8 * dir_my, bx + 5 * dir_my),
                _between(-14.0, 14.0, by * 0.6))
    # Forwards: stay high for the counter but pinch toward the middle
    wing = -10.0 if position_label == "FWD1" else 10.0
    return (_between(12 * dir_my, -25 * dir_my, bx - 12 * dir_my), wing)


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


def _defensive_duty(cfg, position_label, team_id, my_player_id, me_pos,
                    ball_pos, opponents, holder=None) -> dict:
    """MARK the nearest opponent outfielder, else hold the compact anchor.
    The ball carrier is excluded — the designated presser handles them, the
    rest of the team takes away the passing options."""
    ax, ay = _anchor(position_label, team_id, ball_pos)
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


def apply_overrides(commands: list[dict], game_state: dict, team_id: int,
                    my_player_id: int, position_label: str,
                    cfg: OverrideConfig | None) -> tuple[list[dict], str | None]:
    """Rewrite the LLM's first command when it violates a hard tactical rule.
    Returns (commands, override_tag) — tag is None when nothing was changed."""
    if cfg is None or not commands or my_player_id == 0:
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

    # --- 1. I hold the ball -------------------------------------------------
    if i_have:
        d_goal = dist(me_pos, {"x": opp_goal_x, "y": 0})
        if cfg.enforce_shot and d_goal <= cfg.shoot_threshold:
            lane_radius = 1.5 if d_goal <= 25 else 2.5
            aim, _, perp = _best_shot_aim(me_pos, opp_goal_x, opponents)
            point_blank = d_goal <= 15
            if perp >= lane_radius or point_blank:
                desired = aim if perp >= lane_radius else "CENTER"
                if ctype != "SHOOT":
                    return [_cmd("SHOOT", my_player_id, team_id,
                                 {"aim_location": desired, "power": 1.0})], "shoot"
                params["power"] = 1.0
                if params.get("aim_location") != desired:
                    params["aim_location"] = desired
                    return commands, "aim"
                return commands, None
        # Carrying out of range down the middle -> steer to the wing lane
        if (cfg.wing_y and ctype == "MOVE_TO" and d_goal > cfg.shoot_threshold):
            ty = params.get("target_y")
            tx = params.get("target_x")
            toward_opp = isinstance(tx, (int, float)) and (tx - me_pos.get("x", 0)) * -dir_my > 0
            if isinstance(ty, (int, float)) and abs(ty) < 8 and toward_opp:
                params["target_y"] = cfg.wing_y
                return commands, "wing"
        return commands, None

    # --- 2. Teammate holds it: commands that need the ball become support runs
    if teammate_has:
        if ctype in _NEEDS_BALL_CMDS:
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
    if designated:
        return commands, None  # the designated player may chase/press freely

    ball_in_our_half = ball_pos.get("x", 0) * dir_my > 0

    chasing = ctype in _CHASE_CMDS
    if not chasing and ctype == "MOVE_TO":
        tx, ty = params.get("target_x"), params.get("target_y")
        if isinstance(tx, (int, float)) and isinstance(ty, (int, float)):
            chasing = dist({"x": tx, "y": ty}, ball_pos) < cfg.chase_radius

    if cfg.no_chase and chasing:
        if opp_has or ball_in_our_half:
            return [_defensive_duty(cfg, position_label, team_id, my_player_id,
                                    me_pos, ball_pos, opponents, holder)], "no-chase"
        sx, sy = _support_spot(position_label, team_id, ball_pos)
        return [_cmd("MOVE_TO", my_player_id, team_id,
                     {"target_x": round(sx, 1), "target_y": round(sy, 1),
                      "sprint": True})], "no-chase"

    if cfg.compact_anchor and ctype == "MOVE_TO" and (opp_has or ball_in_our_half):
        ax, ay = _anchor(position_label, team_id, ball_pos)
        tx, ty = params.get("target_x"), params.get("target_y")
        bad_target = not (isinstance(tx, (int, float)) and isinstance(ty, (int, float)))
        if bad_target or dist({"x": tx, "y": ty}, {"x": ax, "y": ay}) > cfg.anchor_slack:
            # A wandering defensive MOVE_TO becomes a real defensive job:
            # tight-mark the nearest passing option, or hold the compact line.
            return [_defensive_duty(cfg, position_label, team_id, my_player_id,
                                    me_pos, ball_pos, opponents, holder)], "anchor"

    return commands, None
