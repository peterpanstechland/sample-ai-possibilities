"""Match analytics: heatmaps, player profiles, Bedrock tuning advice."""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from analyze_match import aggregate, split_match_segments as _split_by_clock
from field_coords import engine_to_field, field_definition
from tuning import _load as load_tuning_data

TEAM_DIR = REPO / "ai-team-strands-extremely-aggressive"


def _map_row_xy(mx: float, my: float) -> tuple[float, float]:
    """Engine mx/my from DECISION logs → logical field coordinates."""
    return engine_to_field(mx, my)


def field_bounds(field: dict | None = None, pos: str | None = None) -> dict:
    base = field or field_definition()
    return {**base, "view": pos or "ALL"}


def _engine_ranges(rows: list[dict]) -> dict:
    xs = [float(r[k]) for r in rows for k in ("mx", "bx") if isinstance(r.get(k), (int, float))]
    ys = [float(r[k]) for r in rows for k in ("my", "by") if isinstance(r.get(k), (int, float))]
    out = {}
    if xs:
        out["mx"] = [round(min(xs), 1), round(max(xs), 1)]
    if ys:
        out["my"] = [round(min(ys), 1), round(max(ys), 1)]
    return out
POS_ORDER = ["GK", "DEF", "MID", "FWD1", "FWD2"]
POS_TO_AGENT = {
    "GK": "ai-gk", "DEF": "ai-def", "MID": "ai-mid",
    "FWD1": "ai-fwd1", "FWD2": "ai-fwd2",
}

ADVISOR_MODEL_DEFAULT = "us.amazon.nova-2-lite-v1:0"

ADVISOR_MODELS = [
    {"id": "us.amazon.nova-2-lite-v1:0", "label": "Nova 2 Lite（推荐）",
     "label_en": "Nova 2 Lite (recommended)"},
    {"id": "us.amazon.nova-lite-v1:0", "label": "Nova Lite", "label_en": "Nova Lite"},
    {"id": "us.amazon.nova-micro-v1:0", "label": "Nova Micro（快）",
     "label_en": "Nova Micro (fast)"},
    {"id": "us.anthropic.claude-sonnet-4-6", "label": "Claude Sonnet 4.6",
     "label_en": "Claude Sonnet 4.6"},
    {"id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "label": "Claude Sonnet 4.5",
     "label_en": "Claude Sonnet 4.5"},
    {"id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "label": "Claude Haiku 4.5",
     "label_en": "Claude Haiku 4.5"},
    {"id": "us.anthropic.claude-sonnet-4-20250514-v1:0", "label": "Claude Sonnet 4",
     "label_en": "Claude Sonnet 4"},
    {"id": "us.meta.llama3-1-8b-instruct-v1:0", "label": "Llama 3.1 8B",
     "label_en": "Llama 3.1 8B"},
]


def resolve_advisor_model(model_id: str | None) -> str:
    allowed = {m["id"] for m in ADVISOR_MODELS}
    if model_id and model_id in allowed:
        return model_id
    return ADVISOR_MODEL_DEFAULT

ADVISOR_SYSTEM = """You are a football AI tactics analyst for a 5v5 agentic soccer team.
Given per-player match statistics, their current system prompt excerpt, tuning.json
values, and override rules summary, produce concrete modification advice.

Output ONLY valid JSON:
{
  "players": {
    "GK": {"summary": "...", "prompt_changes": ["..."], "tuning_changes": {"key": value}, "code_changes": ["..."]},
    ...
  },
  "team": {"summary": "...", "priority": ["..."]}
}

Rules:
- Reference actual numbers from the stats (shot discipline, override counts, avg positions).
- prompt_changes: specific lines to add/remove in SYSTEM_PROMPT.
- tuning_changes: only keys that exist in tuning.json bounds.
- code_changes: point to lib/overrides.py or lib/tactics.py behavior if stats show a code-vs-intent gap.
- Be concise; max 3 bullets per section per player."""


def _bin_value(v: float, lo: float, hi: float, n: int) -> int:
    if hi <= lo:
        return 0
    return max(0, min(n - 1, int((v - lo) / (hi - lo) * n)))


def build_heatmap(rows: list[dict], pos: str | None = None,
                  field: dict | None = None,
                  grid_x: int = 22, grid_y: int = 12) -> dict:
    """Activity heatmap from DECISION mx/my fields."""
    bins: dict[str, int] = defaultdict(int)
    trail: list[dict] = []
    shoot_pts: list[dict] = []
    base = field or field_definition()
    bounds = field_bounds(base, pos)
    fx, fy = bounds["x_min"], bounds["y_min"]
    tx, ty = bounds["x_max"], bounds["y_max"]

    for r in rows:
        if pos and r.get("pos") != pos:
            continue
        emx, emy = r.get("mx"), r.get("my")
        if not isinstance(emx, (int, float)) or not isinstance(emy, (int, float)):
            continue
        mx, my = _map_row_xy(float(emx), float(emy))
        ix = _bin_value(mx, fx, tx, grid_x)
        iy = _bin_value(my, fy, ty, grid_y)
        bins[f"{ix},{iy}"] += 1
        pt = {"x": round(mx, 1), "y": round(my, 1),
              "ex": round(float(emx), 1), "ey": round(float(emy), 1),
              "t": r.get("t"), "cmd": r.get("cmd"), "pos": r.get("pos")}
        trail.append(pt)
        if r.get("cmd") == "SHOOT":
            shoot_pts.append(pt)

    max_count = max(bins.values()) if bins else 1
    cells = [{"ix": int(k.split(",")[0]), "iy": int(k.split(",")[1]),
              "count": c, "intensity": round(c / max_count, 3)}
             for k, c in bins.items()]
    return {
        "pos": pos or "ALL",
        "grid": [grid_x, grid_y],
        "bounds": bounds,
        "cells": cells,
        "max": max_count,
        "samples": len(trail),
        "shots": shoot_pts[-40:],
        "trail": trail[-120:],
    }


def _dist_to_goal(mx: float, my: float, goal_x: float) -> float:
    return round(math.hypot(mx - goal_x, my), 1)


def build_player_profile(pos: str, items: list[dict], field: dict) -> dict:
    """Extended per-position stats beyond aggregate()."""
    n = len(items)
    if not n:
        return {"pos": pos, "ticks": 0}

    cmds = Counter(i.get("cmd") for i in items if i.get("cmd"))
    ovs = Counter(i.get("ov") for i in items if i.get("ov"))
    wants = Counter(i.get("want") for i in items if i.get("want"))

    mx_vals, my_vals = [], []
    g_own = field["goal_x_own"]
    g_opp = field["goal_x_opp"]
    dmg_vals, dog_vals = [], []
    for i in items:
        emx, emy = i.get("mx"), i.get("my")
        if not isinstance(emx, (int, float)):
            continue
        emy = float(emy) if isinstance(emy, (int, float)) else 0.0
        mx, my = _map_row_xy(float(emx), emy)
        mx_vals.append(mx)
        my_vals.append(my)
        dmg_vals.append(_dist_to_goal(mx, my, g_own))
        dog_vals.append(_dist_to_goal(mx, my, g_opp))

    def avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    defend = [i for i in items if i.get("ob") == 1]
    attack = [i for i in items if i.get("hb") == 1]
    chances = [i for i in items
               if i.get("hb") == 1 and isinstance(i.get("dg"), (int, float)) and i["dg"] <= 45]

    mid_x = (field["x_min"] + field["x_max"]) / 2
    own_half = sum(1 for mx in mx_vals if mx < mid_x)
    opp_half = sum(1 for mx in mx_vals if mx > mid_x + 0.5)

    return {
        "pos": pos,
        "ticks": n,
        "commands": dict(cmds.most_common(8)),
        "overrides": dict(ovs.most_common(8)),
        "llm_wanted": dict(wants.most_common(6)),
        "avg_position": {"x": avg(mx_vals), "y": avg(my_vals)},
        "avg_dist_own_goal": avg(dmg_vals),
        "avg_dist_opp_goal": avg(dog_vals),
        "defending_ticks": len(defend),
        "holding_ball_ticks": len(attack),
        "shot_chances": len(chances),
        "shots_taken": sum(1 for i in chances if i.get("cmd") == "SHOOT"),
        "shot_discipline_pct": round(100 * sum(1 for i in chances if i.get("cmd") == "SHOOT") / len(chances))
        if chances else None,
        "override_fixes": sum(1 for i in items if i.get("fix") == 1),
        "zone_pct": {
            "own_half": round(100 * own_half / n),
            "opp_half": round(100 * opp_half / n),
        },
        "avg_latency_p50": None,  # filled by aggregate merge
    }


def _extract_prompt(agent_dir: str) -> str:
    main = TEAM_DIR / agent_dir / "src" / "main.py"
    if not main.exists():
        return ""
    text = main.read_text(encoding="utf-8")
    m = re.search(r'SYSTEM_PROMPT\s*=\s*f?"""(.*?)"""', text, re.DOTALL)
    return m.group(1).strip()[:2500] if m else ""


def _tuning_slice(pos: str) -> dict:
    data = load_tuning_data()
    out = dict(data.get("global") or {})
    out.update(data.get(pos) or {})
    return {k: v for k, v in out.items() if isinstance(v, (int, float, bool, str))}


def load_code_context() -> str:
    """Short summary of override priorities for the advisor."""
    ov = (REPO / "lib" / "overrides.py").read_text(encoding="utf-8")
    lines = []
    for marker in ("enforce_shot", "always_blast", "open-lane", "hold-line", "gk-line"):
        if marker in ov:
            lines.append(marker)
    return "override tags in production: " + ", ".join(lines)


GRIND_RESULTS_PATH = REPO / "grind_results.jsonl"


def _parse_log_ts(ts: str | None) -> float | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(ts[:26] if "." in ts[:26] else ts[:19], fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _segment_wall_times(seg: list[dict]) -> tuple[float | None, float | None]:
    times = [_parse_log_ts(r.get("log_ts")) for r in seg]
    times = [t for t in times if t is not None]
    if not times:
        return None, None
    return min(times), max(times)


def _segment_score(seg: list[dict]) -> str:
    hs = max((r.get("hs") or 0) for r in seg)
    as_ = max((r.get("as") or 0) for r in seg)
    return f"{hs}-{as_}"


def _segment_match_id(seg: list[dict]) -> str | None:
    mids = [r["mid"] for r in seg if r.get("mid")]
    if not mids:
        return None
    return Counter(mids).most_common(1)[0][0]


def _load_grind_results() -> list[dict]:
    if not GRIND_RESULTS_PATH.exists():
        return []
    out = []
    for line in GRIND_RESULTS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = entry.get("ts")
        finish = _parse_log_ts(ts.replace("T", " ").replace("+00:00", "") if ts else None)
        if finish is None and ts:
            try:
                finish = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except ValueError:
                finish = None
        entry["_finish_ts"] = finish
        entry["_start_ts"] = (finish - entry["duration_s"]) if finish and entry.get("duration_s") else None
        out.append(entry)
    return out


def _correlate_grind_id(seg: list[dict], grind: list[dict]) -> str | None:
    logged = _segment_match_id(seg)
    if logged:
        return logged
    start, end = _segment_wall_times(seg)
    if start is None or end is None:
        return None
    mid = (start + end) / 2
    best_id, best_gap = None, 999999.0
    for g in grind:
        gs, gf = g.get("_start_ts"), g.get("_finish_ts")
        if gs is None or gf is None:
            continue
        if gs - 60 <= mid <= gf + 60:
            gap = abs(mid - (gs + gf) / 2)
            if gap < best_gap:
                best_gap, best_id = gap, g.get("match_id")
    return best_id


def split_by_grind(rows: list[dict], grind: list[dict] | None = None) -> list[list[dict]]:
    """Split rows into matches using grind_results.jsonl wall-clock windows."""
    grind = grind if grind is not None else _load_grind_results()
    if not grind or not rows:
        return [rows] if rows else []
    ts_rows = [(r, ts) for r in rows if (ts := _parse_log_ts(r.get("log_ts")))]
    if not ts_rows:
        return [rows]
    t_min = min(ts for _, ts in ts_rows)
    t_max = max(ts for _, ts in ts_rows)
    candidates = [
        g for g in grind
        if g.get("_finish_ts") and t_min - 180 <= g["_finish_ts"] <= t_max + 180
    ]
    if len(candidates) < 2:
        return [rows]
    candidates.sort(key=lambda g: g.get("_start_ts") or 0)

    # Non-overlapping boundaries at midpoints between consecutive sessions.
    cuts: list[float] = []
    for i in range(len(candidates) - 1):
        a = candidates[i].get("_finish_ts") or 0
        b = candidates[i + 1].get("_start_ts") or a
        cuts.append((a + b) / 2)

    segments: list[list[dict]] = [[] for _ in candidates]
    for r, ts in ts_rows:
        idx = 0
        for cut in cuts:
            if ts > cut:
                idx += 1
            else:
                break
        segments[idx].append(r)

    out = [seg for seg in segments if len(seg) >= 80]
    return out if len(out) >= 2 else [rows]


def _merge_tiny_segments(segments: list[list[dict]], min_ticks: int = 100) -> list[list[dict]]:
    """Merge fragments produced by clock heuristics into neighboring segments."""
    if not segments:
        return []
    merged: list[list[dict]] = []
    for seg in segments:
        if merged and len(seg) < min_ticks:
            merged[-1].extend(seg)
        else:
            merged.append(list(seg))
    return [s for s in merged if len(s) >= min_ticks] or merged


def split_match_segments(rows: list[dict]) -> list[list[dict]]:
    """Split rows into matches — prefer grind windows, else clock heuristics."""
    if not rows:
        return []
    grind_segs = split_by_grind(rows)
    if len(grind_segs) >= 2 and max(len(s) for s in grind_segs) >= 100:
        return grind_segs
    segments = _split_by_clock(rows)
    if len(segments) <= 1:
        return segments
    return _merge_tiny_segments(segments)


def _grind_report(entry: dict) -> dict:
    """Minimal match report from portal grind_results when CloudWatch rows missing."""
    home = int(entry.get("my_score") or 0)
    away = int(entry.get("opp_score") or 0)
    return {
        "score": {
            "home": home, "away": away, "display": f"{home}-{away}",
            "won": home > away, "draw": home == away, "lost": home < away,
        },
        "possession": {"our_pct": None, "opp_pct": None, "loose_pct": None},
        "territory": {"opp_half_pct": None, "own_half_pct": None, "mid_third_pct": None},
        "goals": [],
        "shots": {"our_attempts": None},
        "game_time_max": None,
        "in_progress": False,
        "tick_samples": 0,
        "from_grind": True,
        "match_id": entry.get("match_id"),
    }


def _ticks_by_time(rows: list[dict]) -> dict[tuple, list[dict]]:
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        by_key[(r.get("t"), r.get("tick"))].append(r)
    return by_key


def _guess_scorer(rows: list[dict], goal_t: float | int, team: str) -> str | None:
    if team != "us":
        return None
    window = [
        r for r in rows
        if isinstance(r.get("t"), (int, float))
        and goal_t - 12 <= r["t"] <= goal_t
        and r.get("cmd") == "SHOOT"
    ]
    if not window:
        window = [
            r for r in rows
            if isinstance(r.get("t"), (int, float))
            and goal_t - 12 <= r["t"] <= goal_t
            and r.get("want") == "SHOOT"
        ]
    if not window:
        return None
    return max(window, key=lambda r: (r.get("t") or 0, r.get("tick") or 0)).get("pos")


def _goal_events(rows: list[dict]) -> list[dict]:
    if not any("hs" in r and "as" in r for r in rows):
        return []
    by_t: dict = defaultdict(list)
    for r in rows:
        t = r.get("t")
        if t is not None and "hs" in r and "as" in r:
            by_t[t].append(r)

    events: list[dict] = []
    last_h, last_a = 0, 0
    for t in sorted(by_t):
        hs = max(r["hs"] for r in by_t[t])
        as_ = max(r["as"] for r in by_t[t])
        while hs > last_h:
            events.append({
                "t": t,
                "minute": f"{int(t)}'",
                "team": "us",
                "scorer": _guess_scorer(rows, t, "us"),
                "score_after": f"{hs}-{as_}",
            })
            last_h += 1
        while as_ > last_a:
            events.append({
                "t": t,
                "minute": f"{int(t)}'",
                "team": "opp",
                "scorer": None,
                "score_after": f"{hs}-{as_}",
            })
            last_a += 1
    return events


def build_match_report(rows: list[dict]) -> dict | None:
    """Score, possession, territory, goal timeline from DECISION rows."""
    if not rows or not any("hs" in r and "as" in r for r in rows):
        return None

    home = max(int(r.get("hs") or 0) for r in rows)
    away = max(int(r.get("as") or 0) for r in rows)
    max_t = max(int(r.get("t") or 0) for r in rows)
    by_key = _ticks_by_time(rows)

    our_p = opp_p = loose = 0
    for items in by_key.values():
        if any(i.get("hb") == 1 for i in items):
            our_p += 1
        elif any(i.get("ob") == 1 for i in items):
            opp_p += 1
        else:
            loose += 1
    total = our_p + opp_p + loose

    ball_own = ball_opp = ball_mid = 0
    seen_ball: set[tuple] = set()
    for r in rows:
        key = (r.get("t"), r.get("tick"))
        if key in seen_ball or not isinstance(r.get("bx"), (int, float)):
            continue
        seen_ball.add(key)
        fx, _ = engine_to_field(float(r["bx"]), 0.0)
        if fx > 2:
            ball_opp += 1
        elif fx < -2:
            ball_own += 1
        else:
            ball_mid += 1
    ball_total = ball_own + ball_opp + ball_mid

    goals = _goal_events(rows)
    our_shots = sum(1 for r in rows if r.get("cmd") == "SHOOT")

    return {
        "score": {
            "home": home,
            "away": away,
            "display": f"{home}-{away}",
            "won": home > away,
            "draw": home == away,
            "lost": home < away,
        },
        "possession": {
            "our_pct": round(100 * our_p / total) if total else None,
            "opp_pct": round(100 * opp_p / total) if total else None,
            "loose_pct": round(100 * loose / total) if total else None,
        },
        "territory": {
            "opp_half_pct": round(100 * ball_opp / ball_total) if ball_total else None,
            "own_half_pct": round(100 * ball_own / ball_total) if ball_total else None,
            "mid_third_pct": round(100 * ball_mid / ball_total) if ball_total else None,
        },
        "goals": goals,
        "shots": {"our_attempts": our_shots},
        "game_time_max": max_t,
        "in_progress": max_t < 118,
        "tick_samples": total,
    }


def build_match_catalog(segments: list[list[dict]]) -> list[dict]:
    import time as _time
    grind = _load_grind_results()
    catalog: list[dict] = []
    matched_grind_ids: set[str] = set()

    for i, seg in enumerate(segments):
        start, end = _segment_wall_times(seg)
        match_id = _correlate_grind_id(seg, grind)
        if match_id:
            matched_grind_ids.add(match_id)
        report = build_match_report(seg) or {}
        poss = report.get("possession") or {}
        score = report.get("score") or {}
        grind_entry = next((g for g in grind if g.get("match_id") == match_id), None) if match_id else None
        display_score = (
            f"{grind_entry.get('my_score', 0)}-{grind_entry.get('opp_score', 0)}"
            if grind_entry else _segment_score(seg)
        )
        catalog.append({
            "index": len(catalog),
            "segment_index": i,
            "match_id": match_id,
            "score": display_score,
            "home_score": grind_entry.get("my_score") if grind_entry else score.get("home"),
            "away_score": grind_entry.get("opp_score") if grind_entry else score.get("away"),
            "won": grind_entry.get("won") if grind_entry else score.get("won"),
            "possession_our_pct": poss.get("our_pct"),
            "possession_opp_pct": poss.get("opp_pct"),
            "goals_count": len(report.get("goals") or []),
            "ticks": len(seg),
            "game_duration_s": max(r.get("t") or 0 for r in seg),
            "shots": sum(1 for r in seg if r.get("cmd") == "SHOOT"),
            "start_ts": start,
            "end_ts": end,
            "in_progress": i == len(segments) - 1
                and max(r.get("t") or 0 for r in seg) < 118,
            "no_logs": False,
        })

    now = _time.time()
    for g in reversed(grind[-30:]):
        mid = g.get("match_id")
        if not mid or mid in matched_grind_ids:
            continue
        gf = g.get("_finish_ts")
        if gf and now - gf > 48 * 3600:
            continue
        catalog.append({
            "index": len(catalog),
            "segment_index": None,
            "match_id": mid,
            "score": f"{g.get('my_score', 0)}-{g.get('opp_score', 0)}",
            "home_score": g.get("my_score"),
            "away_score": g.get("opp_score"),
            "won": g.get("won"),
            "possession_our_pct": None,
            "possession_opp_pct": None,
            "goals_count": None,
            "ticks": 0,
            "game_duration_s": g.get("duration_s"),
            "shots": None,
            "start_ts": g.get("_start_ts"),
            "end_ts": gf,
            "in_progress": False,
            "no_logs": True,
        })

    catalog.sort(key=lambda c: c.get("end_ts") or c.get("start_ts") or 0, reverse=True)
    for i, c in enumerate(catalog):
        c["index"] = i
    return catalog


def resolve_match_rows(rows: list[dict], match: str | None) -> tuple[list[dict], int | None, str | None]:
    """Filter rows to one match segment. match: None/'all', segment index, or UUID."""
    segments = split_match_segments(rows)
    catalog = build_match_catalog(segments)
    if not match or match == "all":
        return rows, None, None

    for meta in catalog:
        mid = meta.get("match_id")
        si = meta.get("segment_index")
        if mid == match or (si is not None and str(si) == match):
            if meta.get("no_logs") or si is None:
                return [], meta.get("index"), mid
            return segments[si], si, mid

    try:
        idx = int(match)
    except ValueError as e:
        raise ValueError(f"unknown match: {match}") from e
    if idx < 0 or idx >= len(segments):
        raise ValueError(f"match index {idx} out of range (0..{len(segments) - 1})")
    mid = next((m.get("match_id") for m in catalog if m.get("segment_index") == idx), None)
    return segments[idx], idx, mid


def build_analytics_payload(rows: list[dict], match: str | None = None) -> dict:
    segments = split_match_segments(rows)
    catalog = build_match_catalog(segments)
    active_rows, selected_index, selected_id = resolve_match_rows(rows, match)

    agents = aggregate(active_rows)
    agent_by_pos = {a["pos"]: a for a in agents}

    by_pos: dict[str, list[dict]] = defaultdict(list)
    for r in active_rows:
        by_pos[r.get("pos", "?")].append(r)

    field = field_definition()
    engine_range = _engine_ranges(active_rows)
    profiles = []
    heatmaps = {"ALL": build_heatmap(active_rows, field=field)}
    for pos in POS_ORDER:
        items = by_pos.get(pos, [])
        prof = build_player_profile(pos, items, field)
        ag = agent_by_pos.get(pos)
        if ag:
            prof["latency"] = ag.get("latency")
            prof["llm_ratio"] = ag.get("llm_ratio")
            prof["recommendations"] = ag.get("recommendations", [])
            prof["held"] = ag.get("held")
        prof["prompt_excerpt"] = _extract_prompt(POS_TO_AGENT[pos])[:800]
        prof["tuning"] = _tuning_slice(pos)
        profiles.append(prof)
        heatmaps[pos] = build_heatmap(active_rows, pos, field=field)

    match_report = build_match_report(active_rows) if active_rows and (
        selected_index is not None or len(segments) == 1
    ) else None
    if match_report is None and selected_id:
        grind_entry = next(
            (g for g in _load_grind_results() if g.get("match_id") == selected_id),
            None,
        )
        if grind_entry:
            match_report = _grind_report(grind_entry)

    return {
        "ticks": len(active_rows),
        "ticks_total": len(rows),
        "matches_detected": len(segments),
        "matches": catalog[:20],
        "selected_match": selected_index,
        "selected_match_id": selected_id,
        "match_report": match_report,
        "agents": agents,
        "profiles": profiles,
        "heatmaps": heatmaps,
        "field": field,
        "engine_range": engine_range,
        "advisor_models": ADVISOR_MODELS,
        "advisor_model_default": ADVISOR_MODEL_DEFAULT,
        "code_context": load_code_context(),
    }


def _parse_advisor_json(text: str) -> dict:
    """Extract JSON object from Claude response (handles ```json fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("advisor returned non-JSON")
    return json.loads(t[start:end + 1])


def advise_players(payload: dict, region: str = "us-east-1",
                  model_id: str | None = None) -> dict:
    """Call Bedrock for per-player modification advice."""
    from botocore.exceptions import ClientError
    from aws_clients import BEDROCK_US_PROXY_DOMAINS, aws_client, needs_us_proxy

    model = resolve_advisor_model(model_id)
    use_proxy = needs_us_proxy(model)
    brt = aws_client("bedrock-runtime", region, use_proxy=use_proxy)
    user = {
        "stats": payload.get("profiles"),
        "aggregate": payload.get("agents"),
        "matches": payload.get("matches"),
        "code_context": payload.get("code_context"),
        "tuning_global": load_tuning_data().get("global"),
    }
    text = ""
    try:
        resp = brt.converse(
            modelId=model,
            system=[{"text": ADVISOR_SYSTEM}],
            messages=[{"role": "user",
                       "content": [{"text": json.dumps(user, ensure_ascii=False, default=str)[:12000]}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.2},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        out = _parse_advisor_json(text)
        out["model"] = model
        return out
    except ValueError as e:
        return {"error": str(e), "raw": text[:500]}
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        hint = ""
        if code == "AccessDeniedException" and "not available for this account" in msg:
            hint = (" · 该模型未对本 AWS 账号开通（Workshop/试用账号常见）。"
                    "请在 Bedrock 控制台 → Model access 申请，或改用 Claude Sonnet 4.6 / Nova 2 Lite。")
        elif "unsupported countries" in msg.lower() or code == "ValidationException":
            hint = (" · Claude 需美国出口：在 VPN 中将 Bedrock 域名分流到美国节点，例如 "
                    f"{', '.join(BEDROCK_US_PROXY_DOMAINS[:2])}")
        return {"error": f"Bedrock {code}: {msg}{hint}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
