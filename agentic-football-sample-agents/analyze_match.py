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
"""

import argparse
import json
import os
import time
from collections import Counter, defaultdict

import boto3

LOG_GROUP_PREFIX = "/aws/bedrock-agentcore/runtimes/"

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
            "recommendations": recs,
        })
    return agents


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
    args = ap.parse_args()

    logs = boto3.client("logs", region_name=args.region)
    groups = find_log_groups(logs, args.prefix)
    if not groups:
        print(f"No log groups under {LOG_GROUP_PREFIX} (region {args.region}).")
        return
    print(f"Querying {len(groups)} log group(s), last {args.minutes} min...\n")
    rows = run_query(logs, groups, args.minutes)
    print(analyze(rows))


if __name__ == "__main__":
    main()
