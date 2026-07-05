"""Model bake-off for the per-tick decision call.

Replays real training-ground scenarios through the exact production path
(create_agent -> Strands BedrockModel -> parse_commands) for every candidate
model and measures what actually matters for a 1s game tick:

  - latency p50 / p95 / max (p95 > ~900ms = timeout territory)
  - JSON parse success rate (a beautiful answer we can't parse = fallback)
  - the command it chose per scenario (sanity check: does it SHOOT on a
    clear lane, defend when the opponent has the ball?)

Usage (needs AWS credentials):
  python bench_models.py                        # default candidate set
  python bench_models.py --calls 9
  python bench_models.py --models us.amazon.nova-micro-v1:0,us.amazon.nova-lite-v1:0
"""

import argparse
import copy
import json
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE / "lib"))

# training_ground mocks bedrock_agentcore on import and gives us the agent
# module loader + the scenario bank the cloud agents are tested against.
from training_ground import load_agent_module, build_scenarios, TEAM_ID  # noqa: E402
from state import summarize_state  # noqa: E402
from tactics import tactics_report  # noqa: E402
from parsing import parse_commands  # noqa: E402
from agent_base import create_agent  # noqa: E402

CANDIDATES = [
    "us.amazon.nova-micro-v1:0",            # current baseline
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "us.anthropic.claude-3-haiku-20240307-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.meta.llama3-2-3b-instruct-v1:0",
    "us.meta.llama3-1-8b-instruct-v1:0",
]

# Three situations that cover the decision space: holding the ball in range
# (must SHOOT), defending a carrier in our half, chasing a free ball.
SCENARIO_NAMES = ("attack_fwd1_x25_y0", "defend_opp_x-30", "free_ball_mid")
PLAYER_ID, LABEL = 3, "FWD1"


def percentile(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, round(p / 100 * (len(vals) - 1))))
    return vals[k]


def build_prompts():
    scenarios = {name: gs for name, gs in build_scenarios() if name in SCENARIO_NAMES}
    prompts = {}
    for name, gs in scenarios.items():
        gs = copy.deepcopy(gs)
        summary = summarize_state(gs, TEAM_ID, PLAYER_ID, LABEL)
        tactics = tactics_report(gs, TEAM_ID, PLAYER_ID, LABEL)
        prompts[name] = f"{summary}\n\n{tactics}" if tactics else summary
    return prompts


def bench_model(model_id, system_prompt, prompts, calls_per_scenario):
    try:
        agent = create_agent(system_prompt, model_id=model_id)
    except Exception as e:  # noqa: BLE001
        return {"model": model_id, "error": f"create: {e}"}

    lat, ok, bad, errors = [], 0, [], []
    cmd_by_scenario = {name: Counter() for name in prompts}
    total = 0
    for rnd in range(calls_per_scenario + 1):  # round 0 = warmup, not counted
        for name, prompt in prompts.items():
            try:
                agent.messages = []
                t0 = time.perf_counter()
                response = str(agent(prompt))
                ms = round((time.perf_counter() - t0) * 1000)
            except Exception as e:  # noqa: BLE001
                if rnd > 0:
                    errors.append(str(e)[:90])
                time.sleep(2)
                continue
            if rnd == 0:
                continue
            total += 1
            lat.append(ms)
            cmds = parse_commands(response, TEAM_ID, PLAYER_ID)
            if cmds:
                ok += 1
                cmd_by_scenario[name][cmds[0].get("commandType")] += 1
            else:
                bad.append(response[:80].replace("\n", " "))
            time.sleep(0.15)

    return {
        "model": model_id,
        "calls": total,
        "parse_ok": ok,
        "p50": percentile(lat, 50),
        "p95": percentile(lat, 95),
        "max": max(lat) if lat else None,
        "cmds": {n: dict(c.most_common(3)) for n, c in cmd_by_scenario.items()},
        "bad_samples": bad[:2],
        "errors": errors[:2],
        "n_errors": len(errors),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=8,
                    help="measured calls per scenario (default 8 -> 24/model)")
    ap.add_argument("--models", default=",".join(CANDIDATES))
    args = ap.parse_args()

    team_dir = BASE / "ai-team-strands-extremely-aggressive"
    mod = load_agent_module(team_dir, "ai-fwd1")
    system_prompt = mod.SYSTEM_PROMPT
    prompts = build_prompts()
    print(f"scenarios: {list(prompts)} | {args.calls} measured calls each "
          f"(+1 warmup round)\n")

    results = []
    for model_id in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"benchmarking {model_id} ...")
        r = bench_model(model_id, system_prompt, prompts, args.calls)
        results.append(r)
        if r.get("error"):
            print(f"  ERROR {r['error']}")
        else:
            rate = f"{r['parse_ok']}/{r['calls']}"
            print(f"  p50={r['p50']}ms p95={r['p95']}ms max={r['max']}ms "
                  f"parse={rate} errors={r['n_errors']}")

    out = BASE / "bench_models_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nfull results -> {out.name}")

    print("\n=== summary (sorted by p95) ===")
    scored = [r for r in results if not r.get("error") and r.get("p50") is not None]
    for r in sorted(scored, key=lambda x: x["p95"] or 9e9):
        rate = 100 * r["parse_ok"] // r["calls"] if r["calls"] else 0
        print(f"  {r['model']:<48} p50={str(r['p50']):>5} p95={str(r['p95']):>5} "
              f"parse={rate:>3}% errs={r['n_errors']}")


if __name__ == "__main__":
    main()
