"""Local latency benchmark for the extremely-aggressive team.

Imports each agent's real config (model + prompt + inference params) from its
main.py, then measures end-to-end LLM decision latency against Bedrock.

Usage:
    python bench_latency.py            # all 5 agents, 3 rounds each
    python bench_latency.py ai-gk      # single agent
    python bench_latency.py -n 5       # 5 rounds per agent
"""

import importlib.util
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from test_helpers import mock_agentcore, GAME_STATE, TEAM_ID
mock_agentcore()

from state import summarize_state
from parsing import parse_commands

AGENTS = ["ai-gk", "ai-def", "ai-mid", "ai-fwd1", "ai-fwd2"]


def load_agent_module(agent_dir: str):
    """Import <agent_dir>/src/main.py as an isolated module."""
    path = os.path.join(HERE, agent_dir, "src", "main.py")
    name = f"main_{agent_dir.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def bench_agent(agent_dir: str, rounds: int) -> dict:
    mod = load_agent_module(agent_dir)
    agent = mod.agent
    pid = mod.MY_PLAYER_ID
    label = mod.POSITION_LABEL

    model_id = agent.model.config.get("model_id", "?")
    max_tokens = agent.model.config.get("max_tokens", "-")
    prompt_chars = len(mod.SYSTEM_PROMPT)

    summary = summarize_state(GAME_STATE, TEAM_ID, pid, label)

    latencies, parsed_ok, commands_seen = [], 0, []
    for i in range(rounds):
        agent.messages = []  # fresh conversation each tick, same as runtime
        t0 = time.perf_counter()
        response = agent(summary)
        ms = (time.perf_counter() - t0) * 1000
        latencies.append(ms)

        cmds = parse_commands(str(response), TEAM_ID, pid)
        if cmds and all(c["playerId"] == pid for c in cmds):
            parsed_ok += 1
            commands_seen.append(cmds[0].get("commandType"))
        else:
            commands_seen.append(f"PARSE_FAIL:{str(response)[:60]!r}")

    return {
        "agent": agent_dir,
        "label": label,
        "model": model_id.replace("us.amazon.", "").replace("-v1:0", ""),
        "max_tokens": max_tokens,
        "prompt_chars": prompt_chars,
        "latencies": latencies,
        "parsed_ok": parsed_ok,
        "rounds": rounds,
        "commands": commands_seen,
    }


def main():
    args = [a for a in sys.argv[1:]]
    rounds = 3
    if "-n" in args:
        idx = args.index("-n")
        rounds = int(args[idx + 1])
        del args[idx:idx + 2]
    targets = args if args else AGENTS

    print(f"Benchmarking {len(targets)} agent(s), {rounds} round(s) each\n")
    results = []
    for agent_dir in targets:
        print(f"--- {agent_dir} ---")
        try:
            r = bench_agent(agent_dir, rounds)
        except Exception as e:
            print(f"  ERROR: {e}\n")
            continue
        results.append(r)
        lat = r["latencies"]
        print(f"  model={r['model']} max_tokens={r['max_tokens']} prompt={r['prompt_chars']} chars")
        print(f"  latency ms: min={min(lat):.0f} median={statistics.median(lat):.0f} max={max(lat):.0f}")
        print(f"  parse: {r['parsed_ok']}/{r['rounds']} ok, commands={r['commands']}")
        print()

    if results:
        print("=" * 62)
        print(f"{'agent':<9} {'model':<11} {'median':>7} {'min':>6} {'max':>6}  parse")
        print("-" * 62)
        for r in results:
            lat = r["latencies"]
            print(f"{r['agent']:<9} {r['model']:<11} {statistics.median(lat):>6.0f}m {min(lat):>5.0f}m {max(lat):>5.0f}m  {r['parsed_ok']}/{r['rounds']}")
        all_medians = [statistics.median(r["latencies"]) for r in results]
        print("-" * 62)
        print(f"team median of medians: {statistics.median(all_medians):.0f} ms")


if __name__ == "__main__":
    main()
