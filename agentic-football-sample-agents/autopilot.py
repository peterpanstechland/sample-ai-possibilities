"""Self-improving match loop for the extremely-aggressive team.

One iteration = one closed feedback cycle:

  1. MATCH    portal_bot (Playwright) starts a practice match vs a portal bot
              and waits for the final whistle -> score, W/L, match report.
  2. OBSERVE  pull the match window's DECISION logs from CloudWatch and distill
              KPIs (shot discipline, far-shot waste, possession height, siege
              indicators, override counts).
  3. TUNE     adjust lib/tuning.json inside safe BOUNDS — a deterministic rule
              tuner by default, optionally an LLM advisor (--llm-advisor) that
              reads the KPIs and proposes bounded deltas ("experience").
  4. DEPLOY   redeploy the 5 agents through WSL (deploy-wsl.sh) so the next
              match plays with the tuned parameters.
  5. RECORD   append everything to autopilot_history.jsonl — the loop's memory;
              consecutive losses with the same tuning force exploration, wins
              freeze the config.

Usage:
  python portal_bot.py setup --team-code <CODE>   # one-time portal login
  python autopilot.py --iterations 3              # three full cycles
  python autopilot.py --bots aggressive,defensive # rotate opponents
  python autopilot.py --once --skip-deploy        # match + analyze + tune only
  python autopilot.py --llm-advisor               # Nova proposes the tuning
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import boto3

REPO = Path(__file__).parent
sys.path.insert(0, str(REPO / "lib"))

import tuning as tuning_mod  # noqa: E402
from analyze_match import find_log_groups, run_query  # noqa: E402
from portal_bot import BOTS, PortalError, play_one_match  # noqa: E402

TUNING_PATH = REPO / "lib" / "tuning.json"
HISTORY_PATH = REPO / "autopilot_history.jsonl"
LOG_DIR = REPO / "autopilot-logs"
AGENTS = ("ai-gk", "ai-def", "ai-mid", "ai-fwd1", "ai-fwd2")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
LOG_PREFIX = "agg_"  # aggressive team runtime log groups


# --- 2. OBSERVE -----------------------------------------------------------------

def collect_kpis(minutes: int) -> dict:
    """Distill the last `minutes` of DECISION logs into tuner-ready KPIs."""
    logs = boto3.session.Session().client("logs", region_name=REGION)
    groups = find_log_groups(logs, LOG_PREFIX)
    if not groups:
        return {"error": f"no log groups with prefix {LOG_PREFIX}"}
    rows = run_query(logs, groups, minutes)
    if not rows:
        return {"error": "no DECISION rows in window"}

    by_pos = defaultdict(list)
    for r in rows:
        by_pos[r.get("pos", "?")].append(r)

    positions, all_shots, all_far = {}, 0, 0
    for pos, items in by_pos.items():
        held = [r for r in items if r.get("hb") == 1]
        dgs = sorted(r["dg"] for r in held if isinstance(r.get("dg"), (int, float)))
        chances = [r for r in held
                   if isinstance(r.get("dg"), (int, float)) and r["dg"] <= 45]
        shots = [r for r in items if r.get("cmd") == "SHOOT"]
        far = sum(1 for r in shots
                  if isinstance(r.get("dg"), (int, float)) and r["dg"] > 45)
        all_shots += len(shots)
        all_far += far
        positions[pos] = {
            "ticks": len(items),
            "held": len(held),
            "med_dg": dgs[len(dgs) // 2] if dgs else None,
            "in_range_ticks": len(chances),
            "shots": len(shots),
            "shots_far": far,
            "chance_shots": sum(1 for r in chances if r.get("cmd") == "SHOOT"),
            "overrides": dict(Counter(r.get("ov") for r in items if r.get("ov"))),
            "cmds": dict(Counter(r.get("cmd") for r in items).most_common(5)),
        }

    fw = [r for r in rows if r.get("pos") in ("FWD1", "FWD2")
          and isinstance(r.get("dg"), (int, float))]
    fw_deep = sum(1 for r in fw if r["dg"] >= 60)
    gk = by_pos.get("GK", [])
    gk_busy = sum(1 for r in gk
                  if r.get("cmd") in ("INTERCEPT", "SLIDE_TACKLE", "PRESS_BALL",
                                      "CLEAR_BALL"))
    ticks_seen, ticks_held = set(), set()
    for r in rows:
        t = r.get("t")
        if t is None:
            continue
        ticks_seen.add(t)
        if r.get("hb") == 1:
            ticks_held.add(t)

    return {
        "rows": len(rows),
        "positions": positions,
        "team": {
            "shots": all_shots,
            "far_shot_ratio": round(all_far / all_shots, 2) if all_shots else 0.0,
            "forwards_deep_pct": round(100 * fw_deep / len(fw)) if fw else None,
            "gk_emergency_pct": round(100 * gk_busy / len(gk)) if gk else None,
            "possession_pct": (round(100 * len(ticks_held) / len(ticks_seen))
                               if ticks_seen else None),
        },
    }


# --- 3. TUNE --------------------------------------------------------------------

def _read_tuning() -> dict:
    try:
        return json.loads(TUNING_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_tuning(data: dict):
    TUNING_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")


def _bump(data: dict, scope: str, key: str, delta: float, notes: list[str]):
    """data[scope][key] += delta, starting from the OverrideConfig default and
    clamped to BOUNDS. Records a human-readable note when the value moves."""
    from overrides import OverrideConfig
    cur = (data.get(scope) or {}).get(key)
    if cur is None:
        cur = (data.get("global") or {}).get(key)
    if cur is None:
        cur = getattr(OverrideConfig(), key, 0)
    new = tuning_mod.clamp(key, (cur or 0) + delta)
    if new == cur:
        return
    data.setdefault(scope, {})[key] = new
    notes.append(f"{scope}.{key}: {cur} -> {new}")


def rule_tuner(result: dict, kpis: dict, data: dict) -> tuple[dict, list[str]]:
    """Deterministic, bounded reactions to a finished match. Mirrors how we
    tuned by hand across iterations 6-9."""
    notes: list[str] = []
    data = json.loads(json.dumps(data))  # deep copy
    if result.get("won"):
        notes.append("won — configuration frozen")
        return data, notes

    my = result.get("my_score") or 0
    opp = result.get("opp_score") or 0
    team = kpis.get("team", {})
    positions = kpis.get("positions", {})

    if opp >= 3:
        # Getting carved open: trigger the counter/deep-anchor posture earlier
        # and extend how far off-ball players will chase a mark.
        _bump(data, "global", "press_bodies", -1, notes)
        _bump(data, "global", "mark_radius", +2.0, notes)

    if (team.get("far_shot_ratio") or 0) > 0.4:
        # Most shots are 45+ prayers: demand a more open GK before long shots
        # and shorten the band where they are allowed.
        _bump(data, "global", "longshot_max", -2.0, notes)
        _bump(data, "global", "gk_out_dist", +1.0, notes)

    if my == 0 and team.get("shots", 0) < 8:
        # Toothless: start forcing shots from slightly further out.
        _bump(data, "global", "shoot_threshold", +2.0, notes)

    if (team.get("possession_pct") or 100) < 35:
        # Can't keep the ball: accept shorter outlet passes to escape faster.
        _bump(data, "global", "outlet_min_gain", -2.0, notes)

    if (team.get("forwards_deep_pct") or 0) > 50:
        # Forwards defending in our box all game: free them up as outlets.
        _bump(data, "global", "press_bodies", -1, notes)

    mid = positions.get("MID", {})
    if mid.get("in_range_ticks", 0) >= 3 and mid.get("chance_shots", 0) == 0:
        _bump(data, "MID", "shoot_threshold", +2.0, notes)

    if not notes:
        # Lost but nothing pathological — widen the shot envelope a touch so
        # consecutive stalemates still explore instead of replaying the loss.
        _bump(data, "global", "shoot_threshold", +1.0, notes)
        notes.append("no dominant failure signal — small exploration step")
    return data, notes


ADVISOR_PROMPT = """You tune a robot-football team between matches by editing
numeric parameters. Rules of the game for you:
- Only propose values inside the given bounds. Booleans/strings are off-limits.
- Small steps (one or two parameters, small deltas) beat big jumps.
- Reply with ONLY a JSON object: {"changes": {"global": {..}, "MID": {..}},
  "reason": "<one short sentence>"} — scopes: global, GK, DEF, MID, FWD1, FWD2.

Parameter meanings:
  shoot_threshold  force-shoot distance (bigger = shoot from further out)
  longshot_max     max distance for opportunistic long shots when GK is out
  gk_out_dist      how far the opp GK must be off his line to justify them
  outlet_min_gain  min territorial gain for a counter outlet pass (smaller =
                   easier escape passes under pressure)
  press_bodies     opponents in our half that flips us into counter mode
                   (smaller = go defensive earlier)
  chase_radius     ball-chase detection radius for non-designated players
  anchor_slack     how far a defensive MOVE_TO may drift from the anchor
  mark_radius      max distance to pick up a man to MARK
  wing_y           wing lane forwards are steered into when carrying centrally
"""


def llm_advisor(result: dict, kpis: dict, data: dict) -> tuple[dict, list[str]] | None:
    """Ask Nova Lite for bounded tuning deltas. Returns None on any failure —
    the caller falls back to the rule tuner."""
    try:
        brt = boto3.session.Session().client("bedrock-runtime", region_name=REGION)
        payload = {
            "result": {k: result.get(k) for k in
                       ("bot", "my_score", "opp_score", "won")},
            "kpis": kpis,
            "current_tuning": data,
            "bounds": tuning_mod.BOUNDS,
        }
        resp = brt.converse(
            modelId="us.amazon.nova-lite-v1:0",
            system=[{"text": ADVISOR_PROMPT}],
            messages=[{"role": "user",
                       "content": [{"text": json.dumps(payload, default=str)}]}],
            inferenceConfig={"maxTokens": 400, "temperature": 0.2},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        start, end = text.find("{"), text.rfind("}")
        parsed = json.loads(text[start:end + 1])
        changes = parsed.get("changes") or {}
        out = json.loads(json.dumps(data))
        notes = []
        for scope, kv in changes.items():
            if scope not in ("global", "GK", "DEF", "MID", "FWD1", "FWD2"):
                continue
            if not isinstance(kv, dict):
                continue
            for key, val in kv.items():
                if key not in tuning_mod.BOUNDS or not isinstance(val, (int, float)):
                    continue  # numeric, known keys only — the advisor is sandboxed
                new = tuning_mod.clamp(key, val)
                old = (out.get(scope) or {}).get(key)
                if new != old:
                    out.setdefault(scope, {})[key] = new
                    notes.append(f"{scope}.{key}: {old} -> {new} (advisor)")
        if parsed.get("reason"):
            notes.append(f"advisor: {parsed['reason']}")
        return out, notes
    except Exception as e:  # noqa: BLE001 — advisor is best-effort by design
        print(f"  LLM advisor unavailable ({e}); falling back to rule tuner")
        return None


# --- 4. DEPLOY --------------------------------------------------------------------

def deploy(agents=AGENTS, retries: int = 2) -> tuple[bool, str]:
    """Redeploy through WSL, one agent at a time (S3 uploads are flaky enough
    that per-agent retry beats one all-or-nothing run)."""
    LOG_DIR.mkdir(exist_ok=True)
    for agent in agents:
        ok = False
        for attempt in range(1, retries + 1):
            print(f"  deploying {agent} (attempt {attempt}/{retries})...")
            log_file = LOG_DIR / f"deploy-{agent}.log"
            with open(log_file, "w", encoding="utf-8", errors="replace") as f:
                proc = subprocess.run(
                    ["wsl", "bash", "deploy-wsl.sh", "aggressive", agent],
                    cwd=str(REPO), stdout=f, stderr=subprocess.STDOUT,
                    timeout=1800,
                )
            out = log_file.read_text(encoding="utf-8", errors="replace")
            if proc.returncode == 0:
                ok = True
                break
            low = out.lower()
            if "expired" in low and "credential" in low.replace("credentials", "credential"):
                return False, ("AWS credentials expired — refresh them "
                               "(write new tokens into WSL ~/.aws) and rerun.")
            print(f"    {agent} failed (see {log_file.name}), retrying...")
        if not ok:
            return False, f"{agent} failed after {retries} attempts"
    return True, "all agents deployed"


# --- 5. RECORD + main loop ---------------------------------------------------------

def append_history(entry: dict):
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def recent_streak() -> int:
    """Consecutive losses at the tail of history (exploration pressure)."""
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return 0
    streak = 0
    for line in reversed(lines):
        try:
            if json.loads(line).get("result", {}).get("won"):
                break
        except json.JSONDecodeError:
            break
        streak += 1
    return streak


def run_iteration(i: int, bot: str, args) -> dict:
    print(f"\n=== iteration {i}: vs {bot} ({BOTS[bot]}) ===")
    t_start = time.time()

    print("[1/4] playing match via portal...")
    result = play_one_match(bot_variant=bot, headed=args.headed,
                            coach_order=args.coach, timeout_s=args.match_timeout)
    print(f"  final: us {result.get('my_score')} — {result.get('opp_score')} "
          f"{result.get('opp_name') or bot}  ({'WON' if result.get('won') else 'lost'})")

    print("[2/4] pulling DECISION logs from CloudWatch...")
    minutes = max(12, int((time.time() - t_start) / 60) + 6)
    try:
        kpis = collect_kpis(minutes)
    except Exception as e:  # boto/credential problems shouldn't kill the loop
        kpis = {"error": str(e)}
    if kpis.get("error"):
        print(f"  KPI collection failed: {kpis['error']}")
    else:
        t = kpis["team"]
        print(f"  shots={t['shots']} far_ratio={t['far_shot_ratio']} "
              f"possession={t['possession_pct']}% fwd_deep={t['forwards_deep_pct']}%")

    print("[3/4] tuning...")
    before = _read_tuning()
    tuned, notes = before, ["kpis unavailable — tuning unchanged"]
    if not kpis.get("error"):
        out = llm_advisor(result, kpis, before) if args.llm_advisor else None
        tuned, notes = out if out else rule_tuner(result, kpis, before)
    changed = tuned != before
    if changed:
        _write_tuning(tuned)
    for n in notes:
        print(f"  - {n}")

    deployed = False
    if changed and not args.skip_deploy:
        print("[4/4] redeploying tuned agents (this takes a while)...")
        ok, msg = deploy()
        print(f"  {msg}")
        deployed = ok
        if not ok and "expired" in msg:
            raise PortalError(msg)
    else:
        print("[4/4] no deploy needed" if not changed else
              "[4/4] deploy skipped (--skip-deploy)")

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "iteration": i,
        "bot": bot,
        "result": {k: result.get(k) for k in
                   ("id", "my_score", "opp_score", "won", "opp_name", "duration_s")},
        "kpis": kpis,
        "tuning_before": before,
        "tuning_after": tuned,
        "notes": notes,
        "deployed": deployed,
        "loss_streak": 0 if result.get("won") else recent_streak() + 1,
    }
    append_history(entry)
    return entry


def main():
    ap = argparse.ArgumentParser(description="match->analyze->tune->deploy loop")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--once", action="store_true", help="single iteration")
    ap.add_argument("--bots", default="aggressive",
                    help="comma list to rotate, e.g. aggressive,defensive,balanced")
    ap.add_argument("--coach", default=None, help="coach order at kickoff")
    ap.add_argument("--match-timeout", type=int, default=1500)
    ap.add_argument("--skip-deploy", action="store_true",
                    help="tune only; do not redeploy")
    ap.add_argument("--llm-advisor", action="store_true",
                    help="let Nova Lite propose the tuning deltas")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser (watch matches live)")
    args = ap.parse_args()

    bots = [b.strip() for b in args.bots.split(",") if b.strip()]
    unknown = [b for b in bots if b not in BOTS]
    if unknown:
        ap.error(f"unknown bots {unknown}; choose from {sorted(BOTS)}")
    iterations = 1 if args.once else args.iterations

    wins = losses = 0
    for i in range(1, iterations + 1):
        try:
            entry = run_iteration(i, bots[(i - 1) % len(bots)], args)
        except PortalError as e:
            print(f"\nSTOP: {e}")
            break
        except KeyboardInterrupt:
            print("\ninterrupted — history preserved")
            break
        if entry["result"].get("won"):
            wins += 1
        else:
            losses += 1

    print(f"\n=== autopilot done: {wins}W {losses}L "
          f"(history: {HISTORY_PATH.name}) ===")


if __name__ == "__main__":
    main()
