"""Play N portal practice matches back-to-back (no auto-tune/deploy).

Usage:
  python grind_matches.py --count 10 --bot aggressive
  python grind_matches.py --count 10 --bot aggressive --no-live-coach
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from portal_bot import BOTS, PortalError, play_one_match

RESULTS_PATH = Path(__file__).parent / "grind_results.jsonl"


def main():
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description="Play multiple practice matches via portal")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--bot", default="aggressive", choices=list(BOTS))
    ap.add_argument("--coach", default=None)
    ap.add_argument("--no-live-coach", action="store_true")
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--out", type=Path, default=RESULTS_PATH)
    args = ap.parse_args()

    wins = losses = 0
    t0 = time.time()
    print(f"Grinding {args.count} matches vs {BOTS[args.bot]} ({args.bot})…")

    for i in range(1, args.count + 1):
        print(f"\n--- match {i}/{args.count} ---")
        try:
            result = play_one_match(
                bot_variant=args.bot,
                headed=args.headed,
                coach_order=args.coach,
                timeout_s=args.timeout,
                live_coach=not args.no_live_coach,
            )
        except PortalError as e:
            print(f"STOP: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\ninterrupted — partial results saved")
            break

        won = bool(result.get("won"))
        wins += won
        losses += not won
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "n": i,
            "bot": args.bot,
            "match_id": result.get("id"),
            "my_score": result.get("my_score"),
            "opp_score": result.get("opp_score"),
            "won": won,
            "duration_s": result.get("duration_s"),
        }
        args.out.parent.mkdir(exist_ok=True)
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"  score {entry['my_score']}-{entry['opp_score']} "
              f"({'W' if won else 'L'}) · {entry['duration_s']}s")

    elapsed = round(time.time() - t0)
    print(f"\n=== grind done: {wins}W {losses}L in {elapsed}s "
          f"(log: {args.out.name}) ===")
    sys.exit(0 if wins > losses else 1)


if __name__ == "__main__":
    main()
