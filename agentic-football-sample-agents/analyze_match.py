"""Post-match analyzer — turns CloudWatch observability into tuning actions.

Every agent logs one structured line per tick:
  DECISION {"pos":"GK","tick":150,"t":120,"source":"llm","cmd":"MOVE_TO",
            "latency_ms":712,"prompt_chars":1840}

This script pulls those lines from the AgentCore runtime log groups via
CloudWatch Logs Insights and prints a per-agent report:
  - decision source breakdown (llm / parse-fallback / error-fallback / last-resort)
  - LLM latency p50 / p95 / max  (timeout risk)
  - command distribution         (is the GK actually distributing? FWD shooting?)
  - concrete tuning recommendations

Usage (Windows PowerShell or WSL, needs AWS credentials):
  python analyze_match.py                 # last 60 minutes, all runtimes
  python analyze_match.py --minutes 30
  python analyze_match.py --prefix ai_gk  # only runtimes whose name starts with this
  python analyze_match.py --goals         # concede-goal forensics from CloudWatch
  python analyze_match.py --llm-audit     # LLM want vs cmd / override audit
  python analyze_match.py --around 34,109 # manual goal times (legacy logs w/o hs/as)
"""

import argparse
import json
import os
import time
from collections import Counter, defaultdict

import boto3

LOG_GROUP_PREFIX = "/aws/bedrock-agentcore/runtimes/"
HOME_TEAM_ID = 0  # portal practice matches: we are always home

QUERY = """
fields @timestamp, @message, @log
| filter @message like /DECISION /
| sort @timestamp asc
| limit 10000
"""


def find_log_groups(logs, prefix_filter: str) -> list[str]:
    groups = []
    paginator = logs.get_paginator("describe_log_groups")
    for page in paginator.paginate(logGroupNamePrefix=LOG_GROUP_PREFIX):
        for g in page.get("logGroups", []):
            name = g["logGroupName"]
            runtime = name[len(LOG_GROUP_PREFIX):]
            if prefix_filter and not runtime.startswith(prefix_filter):
                continue
            groups.append(name)
    return groups


def run_query(logs, groups: list[str], minutes: int) -> list[dict]:
    end = int(time.time())
    start = end - minutes * 60
    q = logs.start_query(
        logGroupNames=groups[:50],  # Insights caps at 50 groups
        startTime=start,
        endTime=end,
        queryString=QUERY,
    )
    qid = q["queryId"]
    while True:
        res = logs.get_query_results(queryId=qid)
        if res["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(1)
    if res["status"] != "Complete":
        raise RuntimeError(f"Logs Insights query ended with status {res['status']}")

    rows = []
    for fields in res.get("results", []):
        row = {f["field"]: f["value"] for f in fields}
        msg = row.get("@message", "")
        # Runtime log lines are structured JSON; the DECISION payload sits in
        # the inner .message field (quotes escaped in the raw @message).
        try:
            outer = json.loads(msg)
            if isinstance(outer, dict) and isinstance(outer.get("message"), str):
                msg = outer["message"]
        except json.JSONDecodeError:
            pass
        idx = msg.find("DECISION ")
        if idx == -1:
            continue
        try:
            data = json.loads(msg[idx + len("DECISION "):].strip())
        except json.JSONDecodeError:
            continue
        data["_log"] = row.get("@log", "").rsplit(":", 1)[-1]
        if row.get("@timestamp"):
            data["log_ts"] = row["@timestamp"]
        rows.append(data)
    return rows


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, round(p / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def aggregate(rows: list[dict]) -> list[dict]:
    """Group DECISION rows per agent and compute stats + recommendations."""
    by_agent = defaultdict(list)
    for r in rows:
        runtime = r["_log"].replace(LOG_GROUP_PREFIX, "").split("-DEFAULT")[0]
        by_agent[(runtime, r.get("pos", "?"))].append(r)

    agents = []
    for (runtime, pos), items in sorted(by_agent.items()):
        n = len(items)
        sources = Counter(i.get("source") for i in items)
        cmds = Counter(i.get("cmd") for i in items if i.get("cmd"))
        lat = sorted(i["latency_ms"] for i in items
                     if i.get("source") == "llm" and isinstance(i.get("latency_ms"), (int, float)))
        chars = [i["prompt_chars"] for i in items if isinstance(i.get("prompt_chars"), (int, float))]

        # Shot discipline: of ticks where the player HELD the ball within
        # shooting range (45), how many produced a SHOOT? This is the true
        # "are we executing the strategy" number — plain shot counts are
        # diluted by all the ticks spent without the ball.
        chances = [i for i in items
                   if i.get("hb") == 1 and isinstance(i.get("dg"), (int, float)) and i["dg"] <= 45]
        chance_shots = sum(1 for i in chances if i.get("cmd") == "SHOOT")

        # Tactical overrides: ticks where code rewrote the LLM command
        # (shoot/aim/no-chase/anchor/support/wing). High counts are fine for
        # winning but flag how far the raw LLM drifts from the game plan.
        overrides = Counter(i.get("ov") for i in items if i.get("ov"))

        recs = []
        llm_ratio = sources.get("llm", 0) / n
        pf = sources.get("parse-fallback", 0)
        if len(chances) >= 3 and chance_shots / len(chances) < 0.6 and pos != "GK":
            recs.append(f"shot discipline {chance_shots}/{len(chances)}: held the ball in range "
                        f"but didn't shoot — RULE #1 is being ignored, tighten the prompt")
        if pf / n > 0.05:
            recs.append(f"parse-fallback {pf}/{n}: LLM output drifting from pure JSON — "
                        f"tighten the response format section or lower temperature")
        if sources.get("error-fallback", 0) + sources.get("last-resort", 0) > 0:
            recs.append("errors present — check runtime log for stack traces (agent error lines)")
        if lat and percentile(lat, 95) > 900:
            recs.append(f"p95 {percentile(lat, 95)}ms: timeout risk — shrink prompt/state, "
                        f"verify Nova Micro, check history reset")
        if lat and percentile(lat, 95) - percentile(lat, 50) > 400:
            recs.append("latency spread is wide — look for context growth across ticks "
                        "(prompt_chars should stay flat)")
        if pos == "GK" and cmds.get("GK_DISTRIBUTE", 0) == 0 and n > 20:
            recs.append("GK never used GK_DISTRIBUTE — distribution priority may not be firing")
        if pos in ("FWD1", "FWD2", "MID") and cmds.get("SHOOT", 0) == 0 and n > 20:
            recs.append(f"{pos} never shot — check shot-first tactics / TACTICS block injection")
        if pos in ("FWD1", "FWD2", "MID", "DEF") and n > 20 and cmds.get("MOVE_TO", 0) / n > 0.85:
            recs.append(f"{pos} is mostly dribbling/running ({cmds.get('MOVE_TO', 0)}/{n} MOVE_TO) — "
                        f"shoot-first rule may not be firing (check hasBall attribution)")
        if llm_ratio < 0.8:
            recs.append(f"only {round(100 * llm_ratio)}% decisions from LLM — the team is "
                        f"effectively playing on rule-based fallback")

        # Holding-ball observability: LLM intent vs executed command
        held = [i for i in items if i.get("hb") == 1]
        held_stats = None
        if held:
            held_stats = {
                "ticks": len(held),
                "cmds": dict(Counter(i.get("cmd") for i in held).most_common(4)),
                "want": dict(Counter(i.get("want") for i in held if i.get("want")).most_common(4)),
                "ov_count": sum(1 for i in held if i.get("ov")),
            }

        agents.append({
            "pos": pos,
            "runtime": runtime,
            "ticks": n,
            "sources": dict(sources),
            "llm_ratio": round(llm_ratio, 3),
            "latency": {
                "p50": percentile(lat, 50), "p95": percentile(lat, 95),
                "max": lat[-1] if lat else None,
            },
            "prompt_chars": {
                "avg": sum(chars) // len(chars) if chars else None,
                "max": max(chars) if chars else None,
            },
            "commands": dict(cmds.most_common()),
            "shots": cmds.get("SHOOT", 0),
            "discipline": {"chances": len(chances), "shots": chance_shots},
            "overrides": dict(overrides.most_common()),
            "held": held_stats,
            "recommendations": recs,
        })
    return agents


def _parse_log_ts(ts: str | None) -> float | None:
    if not ts:
        return None
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            raw = ts[:26] if "." in ts[:26] else ts[:19]
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _row_sort_key(r: dict) -> tuple:
    ts = _parse_log_ts(r.get("log_ts"))
    return (ts if ts is not None else 0.0, r.get("t") or 0, r.get("tick") or 0)


def split_match_segments(rows: list[dict]) -> list[list[dict]]:
    """Split DECISION rows into separate matches.

    Heuristics: game clock jump back, score reset to 0-0, long wall-clock gap.
    """
    if not rows:
        return []
    ordered = sorted(rows, key=_row_sort_key)
    segments, cur = [], [ordered[0]]
    prev = ordered[0]
    prev_h = int(prev.get("hs") or 0)
    prev_a = int(prev.get("as") or 0)

    for r in ordered[1:]:
        t = r.get("t") or 0
        prev_t = prev.get("t") or 0
        hs = int(r.get("hs") or 0)
        as_ = int(r.get("as") or 0)
        new_match = False

        if t < prev_t - 15:
            new_match = True
        elif hs == 0 and as_ == 0 and (prev_h > 0 or prev_a > 0) and prev_t >= 20:
            new_match = True
        else:
            ts_prev = _parse_log_ts(prev.get("log_ts"))
            ts_cur = _parse_log_ts(r.get("log_ts"))
            # Only split on long gaps after a full match (avoid sparse per-agent logging).
            if ts_prev and ts_cur and ts_cur - ts_prev > 240 and prev_t >= 100:
                new_match = True

        if new_match:
            segments.append(cur)
            cur = [r]
        else:
            cur.append(r)
        prev = r
        prev_h, prev_a = max(prev_h, hs), max(prev_a, as_)

    if cur:
        segments.append(cur)
    return segments


def find_conceded_goals(rows: list[dict], home_team: bool = True) -> list[dict]:
    """Detect opponent goals from hs/as jumps in DECISION logs."""
    if not any("hs" in r and "as" in r for r in rows):
        return []
    by_t = defaultdict(list)
    for r in rows:
        t = r.get("t")
        if t is not None and "hs" in r and "as" in r:
            by_t[t].append(r)

    goals, last_h, last_a = [], 0, 0
    for t in sorted(by_t):
        hs = max(r["hs"] for r in by_t[t])
        as_ = max(r["as"] for r in by_t[t])
        conceded = (as_ > last_a) if home_team else (hs > last_h)
        if conceded:
            goals.append({"t": t, "score": f"{hs}-{as_}", "prev": f"{last_h}-{last_a}"})
        last_h, last_a = hs, as_
    return goals


def _window_rows(rows: list[dict], center_t: int, before: int = 18, after: int = 2) -> list[dict]:
    return [r for r in rows
            if isinstance(r.get("t"), (int, float))
            and center_t - before <= r["t"] <= center_t + after]


def _summarize_concede_window(win: list[dict]) -> dict:
    by_pos = defaultdict(list)
    for r in win:
        by_pos[r.get("pos", "?")].append(r)

    snap = {}
    for pos in ("GK", "DEF", "MID", "FWD1", "FWD2"):
        items = by_pos.get(pos, [])
        if not items:
            continue
        cmds = Counter(r.get("cmd") for r in items)
        ovs = Counter(r.get("ov") for r in items if r.get("ov"))
        last = max(items, key=lambda r: (r.get("t") or 0, r.get("tick") or 0))
        snap[pos] = {
            "ticks": len(items),
            "cmds": dict(cmds.most_common(4)),
            "overrides": dict(ovs.most_common(3)),
            "opp_had_ball": sum(1 for r in items if r.get("ob") == 1),
            "at_goal": {
                "cmd": last.get("cmd"),
                "ov": last.get("ov"),
                "mx": last.get("mx"),
                "my": last.get("my"),
                "dmg": last.get("dmg"),
                "bx": last.get("bx"),
                "by": last.get("by"),
                "ob": last.get("ob"),
            },
        }
    ball_x = [r["bx"] for r in win if isinstance(r.get("bx"), (int, float))]
    ball_y = [r["by"] for r in win if isinstance(r.get("by"), (int, float))]
    return {
        "positions": snap,
        "ball_x_range": (min(ball_x), max(ball_x)) if ball_x else None,
        "ball_y_range": (min(ball_y), max(ball_y)) if ball_y else None,
        "opp_ball_ticks": sum(1 for r in win if r.get("ob") == 1),
    }


def _classify_concede(summary: dict) -> list[str]:
    hints = []
    gk = summary.get("positions", {}).get("GK", {})
    at = (gk.get("at_goal") or {}) if gk else {}
    bx, dmg = at.get("bx"), at.get("dmg")
    ball_rng = summary.get("ball_x_range")

    if at.get("cmd") == "MOVE_TO" and at.get("ov") == "gk-cover":
        hints.append("GK pinned on cover line — not smothering/intercepting")
    if at.get("cmd") not in ("INTERCEPT", "PRESS_BALL", "SLIDE_TACKLE", "GK_DISTRIBUTE"):
        hints.append(f"GK last cmd was {at.get('cmd')} (not a ball-winning action)")
    if isinstance(bx, (int, float)) and bx > 35:
        hints.append(f"ball deep in our box area (bx={bx}) — collapse failed")
    if isinstance(dmg, (int, float)) and dmg > 20:
        hints.append(f"GK far from own goal line (dmg={dmg}) when they scored")
    if ball_rng and ball_rng[1] - ball_rng[0] > 25:
        hints.append(f"fast transition (ball x {ball_rng[0]}->{ball_rng[1]}) — counter or through-ball")

    defs = summary.get("positions", {}).get("DEF", {})
    if defs:
        d_cmds = defs.get("cmds") or {}
        if d_cmds.get("MARK", 0) > d_cmds.get("SLIDE_TACKLE", 0) + d_cmds.get("INTERCEPT", 0):
            hints.append("DEF mostly MARK not tackle/intercept in the build-up")
        if d_cmds.get("MOVE_TO", 0) > d_cmds.get("MARK", 0):
            hints.append("DEF drifting (MOVE_TO) instead of holding the line")

    mids = summary.get("positions", {}).get("MID", {})
    if mids and (mids.get("cmds") or {}).get("MARK", 0) > 3:
        hints.append("MID caught marking — no screen in front of the back line")

    total = sum(p.get("ticks", 0) for p in summary.get("positions", {}).values())
    if total and summary.get("opp_ball_ticks", 0) >= total * 0.4:
        hints.append("opponent had sustained possession in the danger window")

    return hints or ["check raw position snapshot — no strong pattern matched"]


def analyze_conceded_goals(rows: list[dict], manual_times: list[int] | None = None) -> str:
    if not rows:
        return "No DECISION rows — play a match with deployed agents first."

    has_score = any("hs" in r and "as" in r for r in rows)
    out = ["=== CONCEDED GOALS (CloudWatch forensics) ===", ""]
    segments = split_match_segments(rows) or [rows]

    for i, seg in enumerate(segments, 1):
        t_range = [r.get("t") for r in seg if r.get("t") is not None]
        if not t_range:
            continue
        out.append(f"--- match segment {i} (game time {min(t_range)}s-{max(t_range)}s, "
                   f"{len(seg)} ticks) ---")

        if has_score:
            goals = find_conceded_goals(seg)
        elif manual_times:
            goals = [{"t": t, "score": "?", "prev": "?"} for t in manual_times]
            out.append("  (legacy logs: no hs/as — using --around goal times)")
        else:
            out.append("  cannot auto-detect goals: DECISION logs lack hs/as fields.")
            out.append("  redeploy agents, OR pass --around 34,109 with known goal times.")
            out.append("")
            continue

        if not goals:
            out.append("  no conceded goals detected in this segment.")
            out.append("")
            continue

        for g in goals:
            out.append(f"  GOAL AGAINST @ {g['t']}s  (score {g['prev']} -> {g['score']})")
            win = _window_rows(seg, g["t"], before=20, after=2)
            summary = _summarize_concede_window(win)
            if summary.get("ball_x_range"):
                bx0, bx1 = summary["ball_x_range"]
                out.append(f"    ball movement: x {bx0} -> {bx1}  "
                           f"(opp-ball ticks {summary['opp_ball_ticks']}/{len(win)})")
            for pos, info in summary.get("positions", {}).items():
                at = info.get("at_goal") or {}
                out.append(f"    {pos}: cmds {info.get('cmds')}  "
                           f"at goal cmd={at.get('cmd')} ov={at.get('ov')} "
                           f"pos=({at.get('mx')},{at.get('my')}) dmg={at.get('dmg')} "
                           f"ball=({at.get('bx')},{at.get('by')}) opp_ball={at.get('ob')}")
            for hint in _classify_concede(summary):
                out.append(f"    >> {hint}")
            out.append("")

    if not has_score and not manual_times:
        out.append("TIP: after next deploy, DECISION lines include hs/as/bx/by/dmg")
        out.append("     so goals are detected automatically from CloudWatch.")

    return "\n".join(out)


def analyze_llm_audit(rows: list[dict]) -> str:
    """CloudWatch observer: did the LLM output the right command type?"""
    if not rows:
        return "No DECISION rows."

    out = ["=== LLM AUDIT (CloudWatch DECISION logs) ===", ""]
    by_pos = defaultdict(list)
    for r in rows:
        by_pos[r.get("pos", "?")].append(r)

    for pos in sorted(by_pos):
        items = by_pos[pos]
        n = len(items)
        llm = [i for i in items if i.get("source") == "llm"]
        if not llm:
            continue
        out.append(f"--- {pos} ({n} ticks, {len(llm)} from LLM) ---")
        pf = sum(1 for i in items if i.get("source") == "parse-fallback")
        out.append(f"  parse-fallback: {pf}/{n} ({100 * pf // max(1, n)}%)")

        fixed = [i for i in llm if i.get("fix") == 1]
        out.append(f"  override fixed LLM: {len(fixed)}/{len(llm)} "
                   f"({100 * len(fixed) // len(llm)}%)")
        if fixed:
            fixes = Counter(f"{i.get('want')}->{i.get('cmd')} via {i.get('ov')}"
                            for i in fixed)
            out.append(f"  top fixes: {dict(fixes.most_common(5))}")

        want_cmds = Counter(i.get("want") for i in llm if i.get("want"))
        run_cmds = Counter(i.get("cmd") for i in llm)
        out.append(f"  llm wanted: {dict(want_cmds.most_common(5))}")
        out.append(f"  after override: {dict(run_cmds.most_common(5))}")

        held = [i for i in llm if i.get("hb") == 1]
        if held:
            in_snap = [i for i in held
                       if (i.get("edg") or i.get("dg") or 99) <= 58]
            llm_shoot = sum(1 for i in in_snap if i.get("want") == "SHOOT")
            ran_shoot = sum(1 for i in in_snap if i.get("cmd") == "SHOOT")
            out.append(f"  holding + effective range<=58: {len(in_snap)} ticks")
            out.append(f"    llm said SHOOT: {llm_shoot}/{len(in_snap)}  "
                       f"actually SHOOT: {ran_shoot}/{len(in_snap)}")
            dribble = sum(1 for i in in_snap if i.get("want") == "MOVE_TO")
            if dribble:
                out.append(f"    llm wanted MOVE_TO in range: {dribble} "
                           f"(code snap-shot should fix)")

        aligned = sum(1 for i in llm
                      if i.get("want") and i.get("want") == i.get("cmd"))
        with_want = sum(1 for i in llm if i.get("want"))
        if with_want:
            out.append(f"  llm aligned (want==cmd): {aligned}/{with_want} "
                       f"({100 * aligned // with_want}%)")
        out.append("")

    out.append("CloudWatch Insights (live):")
    out.append('  fields @message | filter @message like /DECISION /')
    out.append('    and @message like /"fix":1/ | limit 50')
    out.append('  fields @message | filter @message like /DECISION /')
    out.append('    and @message like /"want":"MOVE_TO"/ and @message like /"cmd":"SHOOT"/')
    return "\n".join(out)


def analyze(rows: list[dict]) -> str:
    if not rows:
        return "No DECISION lines found. Deploy the instrumented agents and play a match first."

    out = []
    for a in aggregate(rows):
        n = a["ticks"]
        out.append(f"=== {a['pos']} ({a['runtime']}) — {n} ticks ===")
        src_line = ", ".join(f"{s}: {c} ({100 * c // n}%)"
                             for s, c in Counter(a["sources"]).most_common())
        out.append(f"  sources: {src_line}")
        if a["latency"]["p50"] is not None:
            out.append(f"  llm latency ms: p50={a['latency']['p50']} "
                       f"p95={a['latency']['p95']} max={a['latency']['max']}")
        if a["prompt_chars"]["avg"] is not None:
            out.append(f"  prompt chars: avg={a['prompt_chars']['avg']} max={a['prompt_chars']['max']}")
        top_cmds = ", ".join(f"{c}: {k}" for c, k in Counter(a["commands"]).most_common(5))
        out.append(f"  commands: {top_cmds}")
        if a["discipline"]["chances"]:
            out.append(f"  shot discipline: {a['discipline']['shots']}/{a['discipline']['chances']} "
                       f"(shots taken / ticks holding ball within 45)")
        if a.get("overrides"):
            ov_line = ", ".join(f"{k}: {v}" for k, v in a["overrides"].items())
            out.append(f"  overrides (code enforced over LLM): {ov_line}")
        # Holding-ball observability: what did the LLM want vs what ran?
        held = a.get("held")
        if held:
            out.append(f"  holding ball ({held['ticks']} ticks): cmd {held['cmds']}")
            if held.get("want"):
                out.append(f"  llm wanted (before override): {held['want']}")
            if held.get("ov_count"):
                out.append(f"  overrides while holding: {held['ov_count']}/{held['ticks']}")
        recs = a["recommendations"]
        out.append("  recommendations:" if recs else "  recommendations: none — healthy")
        for r_ in recs:
            out.append(f"    - {r_}")
        out.append("")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=60, help="look-back window (default 60)")
    ap.add_argument("--prefix", default="", help="runtime name prefix filter, e.g. ai_gk")
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    ap.add_argument("--goals", action="store_true",
                    help="include concede-goal forensics section")
    ap.add_argument("--goals-only", action="store_true",
                    help="only print concede-goal forensics")
    ap.add_argument("--llm-audit", action="store_true",
                    help="LLM want vs cmd / override audit from DECISION logs")
    ap.add_argument("--audit-only", action="store_true",
                    help="only LLM audit + optional goals (skip per-agent report)")
    ap.add_argument("--around", default="",
                    help="manual goal times in seconds, e.g. 34,109 (for logs without hs/as)")
    args = ap.parse_args()

    manual_times = [int(x.strip()) for x in args.around.split(",") if x.strip()]

    logs = boto3.client("logs", region_name=args.region)
    groups = find_log_groups(logs, args.prefix)
    if not groups:
        print(f"No log groups under {LOG_GROUP_PREFIX} (region {args.region}).")
        return
    print(f"Querying {len(groups)} log group(s), last {args.minutes} min...\n")
    rows = run_query(logs, groups, args.minutes)
    if len(rows) >= 10000:
        print(f"WARNING: hit 10k row limit — window may be truncated; narrow --minutes\n")

    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        from cloudwatch_store import append_decisions, store_stats
        added = append_decisions(args.prefix or "all", rows)
        if added:
            st = store_stats(args.prefix or "all")
            print(f"Saved {added} new row(s) locally → {st['dir']} ({st['rows']} total)\n")
    except OSError as e:
        print(f"WARNING: could not save local copy: {e}\n")

    parts = []
    if args.goals or args.goals_only:
        parts.append(analyze_conceded_goals(rows, manual_times or None))
    if args.llm_audit or args.audit_only:
        if parts:
            parts.append("")
        parts.append(analyze_llm_audit(rows))
    if not args.goals_only and not args.audit_only:
        if parts:
            parts.append("")
        parts.append(analyze(rows))
    print("\n".join(parts))


if __name__ == "__main__":
    main()
