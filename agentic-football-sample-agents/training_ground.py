"""Local training ground for the football agents.

Replays a bank of realistic scenarios through the same decision pipeline the
deployed agents run (state summary + scouting report + tactics block + Nova
Micro + parsing + rule fallback) and logs one DECISION row per tick in the
exact shape the cloud agents emit to CloudWatch — so observe_dashboard.py can
show real matches and training runs side by side.

Usage:
  python training_ground.py                # fallback-only (free, no AWS calls)
  python training_ground.py --llm         # real Nova Micro calls (needs creds)
  python training_ground.py --llm --repeat 2
  python training_ground.py --team ai-team-strands-balanced

Supported teams: extremely-aggressive (default), balanced, extremely-defensive.
(memory/gateway teams need live AWS infra and are exercised in real matches.)
"""

import argparse
import copy
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE / "lib"))

from test_helpers import mock_agentcore  # noqa: E402
mock_agentcore()  # must run before any agent main.py import

from state import summarize_state, possession_context  # noqa: E402
from parsing import parse_commands  # noqa: E402
from pattern_tracker import PatternTracker  # noqa: E402
from tactics import tactics_report  # noqa: E402
from overrides import apply_overrides  # noqa: E402
from tuning import apply_tuning  # noqa: E402
from analyze_match import analyze  # noqa: E402

TEAM_ID = 0  # train as HOME, attacking +x
POSITIONS = [("ai-gk", 0, "GK"), ("ai-def", 1, "DEF"), ("ai-mid", 2, "MID"),
             ("ai-fwd1", 3, "FWD1"), ("ai-fwd2", 4, "FWD2")]
TRAINING_DIR = BASE / "training_logs"


# ---------------------------------------------------------------------------
# Scenario bank
# ---------------------------------------------------------------------------

def _player(idx, team, x, y, stamina=85):
    return {"agentId": f"agentId_{idx}", "teamCode": team,
            "position": {"x": x, "y": y}, "velocity": {"x": 0, "y": 0},
            "stamina": stamina, "isSprinting": False}


def _formation(our=None, theirs=None):
    """Base 5v5 formation with per-player overrides {idx: (x, y)}."""
    ours = {0: (-50, 0), 1: (-25, 5), 2: (0, -5), 3: (20, -10), 4: (20, 10)}
    opps = {0: (50, 0), 1: (30, -5), 2: (10, 5), 3: (-15, 8), 4: (-15, -8)}
    ours.update(our or {})
    opps.update(theirs or {})
    return ([_player(i, "home", *ours[i]) for i in range(5)]
            + [_player(i, "away", *opps[i]) for i in range(5)])


def _state(name, players, ball_pos, holder=None, *, free=False, vel=(0, 0),
           score=(0, 0), t=60.0, mode="OPEN_PLAY", chat=None):
    return name, {
        "tick": 0, "gameTime": t, "playMode": mode,
        "score": {"home": score[0], "away": score[1]},
        "ball": {"position": {"x": ball_pos[0], "y": ball_pos[1], "z": 0},
                 "velocity": {"x": vel[0], "y": vel[1], "z": 0},
                 "isFree": free,
                 "possessionAgentId": None if holder is None else f"agentId_{holder[1]}"},
        "players": players,
        "teamChat": chat or [],
    }


def build_scenarios() -> list[tuple[str, dict]]:
    """~20 states covering attack, defense, restarts, free balls, coach orders."""
    s = []

    # Kickoff
    s.append(_state("kickoff", _formation(our={2: (-2, 0), 3: (-5, -8), 4: (-5, 8)}),
                    (0, 0), free=True, mode="KICK_OFF", t=0))

    # Attack ladder — FWD1 carries the ball closer and closer to goal
    for x in (10, 25, 40):
        for y in (-12, 0, 12):
            players = _formation(our={3: (x, y), 4: (x - 3, -y if y else 14), 2: (x - 15, 0)},
                                 theirs={1: (x + 8, y // 2), 2: (x - 5, -y)})
            s.append(_state(f"attack_fwd1_x{x}_y{y}", players, (x, y), holder=("home", 3)))

    # FWD2 wide-right chances
    for x in (30, 45):
        players = _formation(our={4: (x, 10), 3: (x - 4, -12)}, theirs={1: (x + 6, 4)})
        s.append(_state(f"attack_fwd2_x{x}", players, (x, 10), holder=("home", 4)))

    # MID at the edge of range
    players = _formation(our={2: (12, -2), 3: (30, -10), 4: (30, 12)})
    s.append(_state("mid_buildup_x12", players, (12, -2), holder=("home", 2)))

    # DEF counter launch
    players = _formation(our={1: (-20, 3), 3: (15, -10), 4: (18, 12)})
    s.append(_state("def_counter", players, (-20, 3), holder=("home", 1)))

    # GK distribution
    players = _formation(our={0: (-50, 0)})
    s.append(_state("gk_distribute", players, (-50, 0), holder=("home", 0)))

    # Defending: opponent carriers advancing on our goal
    for x in (-15, -30, -42):
        players = _formation(theirs={2: (x, -4), 3: (x + 10, 8), 4: (x + 12, -10)},
                             our={1: (x - 8, 0), 2: (x + 5, 5)})
        s.append(_state(f"defend_opp_x{x}", players, (x, -4), holder=("away", 2)))

    # Free balls rolling through midfield
    s.append(_state("free_ball_mid", _formation(), (5, 3), free=True, vel=(4, -1)))
    s.append(_state("free_ball_our_half", _formation(), (-25, -10), free=True, vel=(-3, 0)))

    # Late game: trailing (must gamble) and leading (see if we stay aggressive)
    players = _formation(our={3: (30, -6), 4: (28, 10)})
    s.append(_state("trailing_late", players, (30, -6), holder=("home", 3),
                    score=(0, 1), t=250))
    players = _formation(theirs={2: (-20, 0)})
    s.append(_state("leading_late_defend", players, (-20, 0), holder=("away", 2),
                    score=(1, 0), t=250))

    # Coach order from the Player Portal
    players = _formation(our={2: (8, 0), 3: (25, -8), 4: (25, 8)})
    s.append(_state("coach_order_press", players, (8, 0), holder=("home", 2),
                    chat=[{"message": "全员压上，拿球就射门"}]))

    return s


# ---------------------------------------------------------------------------
# Agent loading + decision pipeline (mirrors lib/agent_base.create_invoke_handler)
# ---------------------------------------------------------------------------

def load_agent_module(team_dir: Path, agent_dir: str):
    path = team_dir / agent_dir / "src" / "main.py"
    name = f"training_{agent_dir.replace('-', '_')}_main"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_position(mod, pid, label, scenarios, use_llm, team_tag):
    rows = []
    tracker = PatternTracker()
    agent = None
    if use_llm:
        from agent_base import create_agent
        agent = create_agent(mod.SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")

    for i, (scen_name, base_state) in enumerate(scenarios):
        gs = copy.deepcopy(base_state)
        gs["tick"] = i * 2
        gs["gameTime"] = max(gs["gameTime"], i * 4.0)

        summary = summarize_state(gs, TEAM_ID, pid, label)
        tracker.update(gs, TEAM_ID)
        scout = tracker.report(gs, TEAM_ID, label)
        if scout:
            summary = f"{summary}\n\n{scout}"
        tactics = tactics_report(gs, TEAM_ID, pid, label)
        if tactics:
            summary = f"{summary}\n\n{tactics}"

        source, cmds, latency_ms, ov = "fallback", None, None, None
        # Same tuning overlay the deployed handler applies at startup
        override_cfg = apply_tuning(getattr(mod, "OVERRIDE_CONFIG", None), label)
        if use_llm:
            try:
                agent.messages = []
                t0 = time.time()
                response = str(agent(summary))
                latency_ms = round((time.time() - t0) * 1000)
                cmds = parse_commands(response, TEAM_ID, pid)
                source = "llm"
                if cmds:
                    # Same post-LLM tactical enforcement the deployed agents run
                    cmds, ov = apply_overrides(cmds, gs, TEAM_ID, pid, label,
                                               override_cfg)
                else:
                    source = "parse-fallback"
                    cmds = mod.fallback_commands(gs, TEAM_ID, pid)
            except Exception:
                source = "error-fallback"
                cmds = mod.fallback_commands(gs, TEAM_ID, pid)
        else:
            cmds = mod.fallback_commands(gs, TEAM_ID, pid)

        hb, dg = possession_context(gs, TEAM_ID, pid)
        row = {
            "pos": label, "tick": gs["tick"], "t": round(gs["gameTime"]),
            "source": source,
            "cmd": cmds[0].get("commandType") if cmds else None,
            "latency_ms": latency_ms, "prompt_chars": len(summary),
            "hb": hb, "dg": dg,
            "scenario": scen_name,
            "_log": f"training/{team_tag}", "_ts": int(time.time() * 1000),
        }
        if ov:
            row["ov"] = ov
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default="ai-team-strands-extremely-aggressive")
    ap.add_argument("--llm", action="store_true", help="call Nova Micro for real")
    ap.add_argument("--repeat", type=int, default=1, help="run the bank N times")
    args = ap.parse_args()

    team_dir = BASE / args.team
    if not team_dir.is_dir():
        sys.exit(f"team dir not found: {team_dir}")
    team_tag = args.team.replace("ai-team-strands-", "")

    scenarios = build_scenarios() * args.repeat
    mode = "llm" if args.llm else "fallback"
    print(f"Training ground: team={team_tag} mode={mode} "
          f"scenarios={len(scenarios)} x 5 agents = {len(scenarios) * 5} decisions\n")

    mods = {agent_dir: load_agent_module(team_dir, agent_dir)
            for agent_dir, _, _ in POSITIONS}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(run_position, mods[d], pid, label, scenarios,
                               args.llm, team_tag)
                   for d, pid, label in POSITIONS]
        all_rows = [r for f in futures for r in f.result()]
    elapsed = time.time() - t0

    TRAINING_DIR.mkdir(exist_ok=True)
    out = TRAINING_DIR / f"train-{team_tag}-{mode}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for r in all_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{len(all_rows)} decisions in {elapsed:.1f}s -> {out}\n")
    print(analyze(all_rows))
    print("View it on the dashboard: python observe_dashboard.py  ->  数据源: 训练场/对比")


if __name__ == "__main__":
    main()
