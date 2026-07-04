"""Inline tactical computations — the Gateway tools' math without the round trips.

The gateway team exposes shot/pass/space/marking calculators as Lambdas behind
an MCP Gateway. Each tool call costs a full extra LLM turn plus Gateway+Lambda
network hops, and the LLM must hand-copy coordinates into the tool input.
Here the same math runs in-process on the real game state (microseconds) and
the results are injected into the prompt as a short TACTICS block, so the LLM
only makes the final choice instead of computing (or guessing) probabilities.
"""

import math

from state import _player_idx, _is_my_team, get_goal_positions, resolve_holder

GOAL_HALF_WIDTH = 5.0


def _dist(a, b) -> float:
    return math.sqrt((a.get("x", 0) - b.get("x", 0)) ** 2 + (a.get("y", 0) - b.get("y", 0)) ** 2)


def _lane_perp(me_pos, opp_goal_x, opponents, aim_y):
    """Minimum perpendicular distance from any blocking opponent to the shot
    line me_pos -> (opp_goal_x, aim_y). Higher = clearer lane.
    """
    dx_goal = opp_goal_x - me_pos.get("x", 0)
    dy_goal = aim_y - me_pos.get("y", 0)
    length = math.hypot(dx_goal, dy_goal) or 1.0
    best = math.inf
    for o in opponents:
        p = o.get("position", {}) or {}
        px = p.get("x", 0) - me_pos.get("x", 0)
        py = p.get("y", 0) - me_pos.get("y", 0)
        t = (px * dx_goal + py * dy_goal) / (length ** 2)
        if not 0.05 < t < 0.98:  # only count opponents between me and the goal
            continue
        perp = abs((py * dx_goal - px * dy_goal) / length)
        if perp < best:
            best = perp
    return best


def _best_shot_aim(me_pos, opp_goal_x, opponents) -> tuple[str, float, float]:
    """Pick the goal-frame target with the clearest lane. Returns
    (aim_location, aim_y, perp) — perp measures how open that target is.
    Aim locations map to y offsets inside the 10-unit goal frame; the goal
    center is (opp_goal_x, 0), the corners are at y = ±4."""
    # Candidates ordered by preference: CENTER first (biggest goal target),
    # then far corners so the LLM ends up shooting at TR/TL/BR/BL when the
    # keeper is centrally positioned.
    aims = [("CENTER", 0.0), ("TL", -4.0), ("TR", 4.0), ("BL", -4.0), ("BR", 4.0)]
    seen = set()
    best_aim, best_y, best_perp = "CENTER", 0.0, -1.0
    for name, y in aims:
        if y in seen:
            continue
        seen.add(y)
        perp = _lane_perp(me_pos, opp_goal_x, opponents, y)
        if perp > best_perp:
            best_aim, best_y, best_perp = name, y, perp
    return best_aim, best_y, best_perp


def _lane_blocked(me_pos, opp_goal_x, opponents, lane_radius=None) -> tuple[bool, float]:
    """Legacy helper kept for tests: is the CENTER shot line blocked, and by
    how much should we sidestep to clear it? Adaptive lane radius — close-range
    hard shots slip past slight overlaps."""
    dx_goal = opp_goal_x - me_pos.get("x", 0)
    if abs(dx_goal) < 0.1:
        return False, 0.0
    if lane_radius is None:
        d = math.hypot(dx_goal, -me_pos.get("y", 0))
        lane_radius = 1.5 if d <= 25 else 2.5

    center_perp = _lane_perp(me_pos, opp_goal_x, opponents, 0.0)
    if center_perp >= lane_radius:
        return False, 0.0

    for off in (3, -3, 6, -6, 9, -9, 12, -12):
        if _lane_perp(me_pos, opp_goal_x, opponents, me_pos.get("y", 0) + off) >= lane_radius:
            return True, float(off)
    return True, 0.0


def _shot_line(me_pos, opp_gk_pos, opponents, opp_goal_x,
               position_label=None) -> tuple[str, bool, float]:
    """Shot probability + lane check. Also returns (blocked, y_offset) so the
    caller can add a follow-up TACTICS line telling the agent to shift laterally
    before shooting (rather than blindly firing into a defender's shins).

    GK/DEF are exempt from the range gate: their full-power kick doubles as a
    clearance, so holding the ball deep is always "blast it at the frame now" —
    never "carry it into range" (which is how deep possession got swarmed).
    """
    goal = {"x": opp_goal_x, "y": 0}
    d_goal = _dist(me_pos, goal)

    if position_label in ("GK", "DEF"):
        aim, _y, _perp = _best_shot_aim(me_pos, opp_goal_x, opponents)
        return (f"- Shot: BLAST (dist {d_goal:.0f}) -> SHOOT NOW aim {aim} "
                f"power 1.0 — no range limit for you: worst case it's a "
                f"60-unit clearance, best case it's a goal", False, 0.0)

    angle_factor = min(1.0, math.atan2(GOAL_HALF_WIDTH, max(d_goal, 0.1)) / 0.15)
    distance_factor = max(0.0, 1.0 - d_goal / 55.0)
    if opp_gk_pos is not None:
        gk_factor = min(1.0, abs(opp_gk_pos.get("y", 0)) / 8.0) * 0.3
        gk_dist_factor = min(1.0, _dist(opp_gk_pos, goal) / 15.0) * 0.2
    else:
        gk_factor, gk_dist_factor = 0.3, 0.2

    blocker_penalty = 0.0
    for o in opponents:
        d = _dist(me_pos, o.get("position", {}))
        if d < 10:
            blocker_penalty += (10 - d) / 10.0 * 0.15
    blocker_penalty = min(blocker_penalty, 0.4)

    p = max(0.02, min(0.95, distance_factor * 0.45 + angle_factor * 0.25
                      + gk_factor + gk_dist_factor - blocker_penalty))

    # Adaptive radius: close-range hard shots slip past slight overlaps.
    lane_radius = 1.5 if d_goal <= 25 else 2.5
    aim, _aim_y, aim_perp = _best_shot_aim(me_pos, opp_goal_x, opponents)
    lane_clear = aim_perp >= lane_radius

    if d_goal > 45:
        # Counter-attack special: their keeper joined the push and is off his
        # line — a 45-52 unit lob at the open frame is a real chance, and it's
        # the ONLY long shot worth taking (own-half blasts just donate the ball).
        gk_off_line = (opp_gk_pos is not None
                       and _dist(opp_gk_pos, goal) >= 12)
        if d_goal <= 52 and gk_off_line and lane_clear:
            verdict = f"GK OFF LINE — LONG SHOT NOW: aim {aim} power 1.0"
        else:
            verdict = "out of range: do NOT shoot from here — pass forward or carry to dist<=45, then shoot"
        blocked = False
    elif lane_clear:
        # A corner aim through a clear lane is a single-tick shot — never leave
        # a good look on the table just because CENTER is covered.
        verdict = f"LANE CLEAR ({aim}) — SHOOT NOW: aim {aim} power 1.0"
        blocked = False
    elif d_goal <= 15:
        # Point-blank — a full-power CENTER shot beats a defender's shins.
        verdict = "POINT-BLANK — SHOOT NOW: aim CENTER power 1.0"
        blocked = False
    else:
        # Every corner blocked at range — sidestep one tick, then shoot.
        _blocked, y_off = _lane_blocked(me_pos, opp_goal_x, opponents, lane_radius)
        if y_off != 0.0:
            adv_x = me_pos.get("x", 0) + (2 if opp_goal_x > 0 else -2)
            verdict = (f"LANE BLOCKED all corners — first MOVE_TO "
                       f"({adv_x:.0f},{me_pos.get('y',0) + y_off:.0f}) sprint true, "
                       f"then SHOOT next tick")
        else:
            verdict = "LANE BLOCKED all corners — PASS to a free teammate"
        blocked = True
    return (f"- Shot: {round(p * 100)}% (dist {d_goal:.0f} to goal) -> {verdict}",
            blocked, 0.0)


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

    holder = resolve_holder(ball, players)
    i_have_ball = holder is me
    opp_holder_idx = _player_idx(holder) if (holder is not None and not _is_my_team(holder, team_id)) else None

    opp_gk = next((o for o in opponents if _player_idx(o) == 0), None)
    opp_gk_pos = (opp_gk or {}).get("position")

    lines = []
    if i_have_ball:
        shot, _blocked, _y_off = _shot_line(me_pos, opp_gk_pos, opponents,
                                            opp_goal_x, position_label)
        lines.append(shot)
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
