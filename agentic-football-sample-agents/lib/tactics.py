"""Inline tactical computations — the Gateway tools' math without the round trips.

The gateway team exposes shot/pass/space/marking calculators as Lambdas behind
an MCP Gateway. Each tool call costs a full extra LLM turn plus Gateway+Lambda
network hops, and the LLM must hand-copy coordinates into the tool input.
Here the same math runs in-process on the real game state (microseconds) and
the results are injected into the prompt as a short TACTICS block, so the LLM
only makes the final choice instead of computing (or guessing) probabilities.
"""

import math

from state import _player_idx, _is_my_team, _possession_idx, get_goal_positions

GOAL_HALF_WIDTH = 5.0


def _dist(a, b) -> float:
    return math.sqrt((a.get("x", 0) - b.get("x", 0)) ** 2 + (a.get("y", 0) - b.get("y", 0)) ** 2)


def _shot_line(me_pos, opp_gk_pos, opponents, opp_goal_x) -> str:
    """Port of gateway_tools/evaluate_shot.py."""
    goal = {"x": opp_goal_x, "y": 0}
    d_goal = _dist(me_pos, goal)

    angle_factor = min(1.0, math.atan2(GOAL_HALF_WIDTH, max(d_goal, 0.1)) / 0.15)
    distance_factor = max(0.0, 1.0 - d_goal / 55.0)
    if opp_gk_pos is not None:
        gk_factor = min(1.0, abs(opp_gk_pos.get("y", 0)) / 8.0) * 0.3
        gk_dist_factor = min(1.0, _dist(opp_gk_pos, goal) / 15.0) * 0.2
        gk_y = opp_gk_pos.get("y", 0)
    else:
        gk_factor, gk_dist_factor, gk_y = 0.3, 0.2, 0.0

    blocker_penalty = 0.0
    for o in opponents:
        d = _dist(me_pos, o.get("position", {}))
        if d < 10:
            blocker_penalty += (10 - d) / 10.0 * 0.15
    blocker_penalty = min(blocker_penalty, 0.4)

    p = max(0.02, min(0.95, distance_factor * 0.45 + angle_factor * 0.25
                      + gk_factor + gk_dist_factor - blocker_penalty))

    my_y = me_pos.get("y", 0)
    if gk_y > 1:
        aim = "BL" if my_y > 0 else "BR"
    elif gk_y < -1:
        aim = "TL" if my_y > 0 else "TR"
    else:
        aim = "TR" if my_y <= 0 else "TL"
    power = min(1.0, 0.6 + d_goal / 80.0)

    verdict = "SHOOT NOW" if p > 0.25 else "low, prefer pass"
    return f"- Shot: {round(p * 100)}% from here (dist {d_goal:.0f}), aim {aim} power {power:.1f} -> {verdict}"


def _pass_line(me_pos, my_id, teammates, opponents) -> str:
    """Port of gateway_tools/calculate_pass_options.py — top 2 options."""
    opp_positions = [o.get("position", {}) for o in opponents]
    options = []
    for tm in teammates:
        tid = _player_idx(tm)
        if tid == my_id:
            continue
        tm_pos = tm.get("position", {})
        pass_dist = _dist(me_pos, tm_pos)

        risk = 0.0
        if pass_dist >= 1:
            dx = tm_pos.get("x", 0) - me_pos.get("x", 0)
            dy = tm_pos.get("y", 0) - me_pos.get("y", 0)
            for op in opp_positions:
                ox = op.get("x", 0) - me_pos.get("x", 0)
                oy = op.get("y", 0) - me_pos.get("y", 0)
                t = max(0, min(1, (ox * dx + oy * dy) / (pass_dist ** 2)))
                lane = math.sqrt((op.get("x", 0) - (me_pos.get("x", 0) + t * dx)) ** 2
                                 + (op.get("y", 0) - (me_pos.get("y", 0) + t * dy)) ** 2)
                if lane < 8:
                    risk = max(risk, 1.0 - lane / 8.0)
            risk = min(risk, 0.95)

        success = max(0.05, 1.0 - risk - pass_dist / 120.0)
        ptype = "GROUND" if pass_dist < 20 else ("THROUGH" if success > 0.5 else "AERIAL")
        options.append((success, tid, ptype))

    if not options:
        return ""
    options.sort(reverse=True)
    best = ", ".join(f"P{tid} {round(s * 100)}% {t}" for s, tid, t in options[:2])
    return f"- Best passes: {best}"


def _mark_line(me_pos, opponents, ball, my_goal_x, opp_holder_idx) -> str:
    """Port of gateway_tools/get_defensive_assignment.py — top threat only.

    Unlike the Lambda tool, the possession bonus is team-aware: it only applies
    when the holder actually is an opponent (ids 0-4 repeat across both teams).
    """
    my_goal = {"x": my_goal_x, "y": 0}
    ball_pos = ball.get("position", {}) or {}

    best = None
    for o in opponents:
        pos = o.get("position", {})
        oid = _player_idx(o)
        threat = max(0.0, 1.0 - _dist(pos, my_goal) / 80.0)
        d_ball = _dist(pos, ball_pos)
        threat += 0.3 if d_ball < 10 else (0.15 if d_ball < 20 else 0.0)
        has_ball = opp_holder_idx is not None and oid == opp_holder_idx
        if has_ball:
            threat += 0.4
        if best is None or threat > best[0]:
            best = (threat, oid, has_ball)

    if best is None:
        return ""
    threat, oid, has_ball = best
    tightness = "TIGHT" if threat > 0.7 else "LOOSE"
    ball_note = ", has ball" if has_ball else ""
    return f"- Top threat: P{oid} (score {threat:.2f}{ball_note}) -> MARK {tightness} or intercept"


def _space_line(me_pos, opponents, team_id) -> str:
    """Port of gateway_tools/find_open_space.py — attack zone, 5-unit grid."""
    opp_positions = [o.get("position", {}) for o in opponents]
    x_min, x_max = (15, 52) if team_id == 0 else (-52, -15)

    best_point, best_score, best_min = None, -1e9, 0.0
    for x in range(x_min, x_max + 1, 5):
        for y in range(-30, 31, 5):
            pt = {"x": x, "y": y}
            min_opp = min((_dist(pt, op) for op in opp_positions), default=999.0)
            score = min_opp - _dist(pt, me_pos) * 0.15
            if score > best_score:
                best_score, best_point, best_min = score, pt, min_opp

    if best_point is None:
        return ""
    return (f"- Open space: ({best_point['x']},{best_point['y']}) "
            f"nearest opp {best_min:.0f} away -> MOVE_TO there if not attacking the ball")


def tactics_report(game_state: dict, team_id: int, my_player_id: int, position_label: str) -> str:
    """Build a <=3-line TACTICS block. Empty string when nothing useful."""
    ball = game_state.get("ball", {}) or {}
    players = game_state.get("players", []) or []

    my_team = [p for p in players if _is_my_team(p, team_id)]
    opponents = [p for p in players if not _is_my_team(p, team_id)]
    me = next((p for p in my_team if _player_idx(p) == my_player_id), None)
    if me is None:
        return ""
    me_pos = me.get("position", {}) or {}

    my_goal_x, opp_goal_x = get_goal_positions(team_id)

    holder_idx = _possession_idx(ball)
    holder = None
    if holder_idx is not None:
        holder = next((q for q in players if _player_idx(q) == holder_idx), None)
    i_have_ball = holder is not None and holder_idx == my_player_id and _is_my_team(holder, team_id)
    opp_holder_idx = holder_idx if (holder is not None and not _is_my_team(holder, team_id)) else None

    opp_gk = next((o for o in opponents if _player_idx(o) == 0), None)
    opp_gk_pos = (opp_gk or {}).get("position")

    lines = []
    if i_have_ball:
        lines.append(_shot_line(me_pos, opp_gk_pos, opponents, opp_goal_x))
        pass_line = _pass_line(me_pos, my_player_id, my_team, opponents)
        if pass_line:
            lines.append(pass_line)
    elif position_label in ("GK", "DEF"):
        mark = _mark_line(me_pos, opponents, ball, my_goal_x, opp_holder_idx)
        if mark:
            lines.append(mark)
    else:  # MID / FWD off the ball: where to run
        space = _space_line(me_pos, opponents, team_id)
        if space:
            lines.append(space)

    if not lines:
        return ""
    return "TACTICS (computed):\n" + "\n".join(lines)
