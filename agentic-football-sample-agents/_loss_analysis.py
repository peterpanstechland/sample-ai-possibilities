"""One-off: why do we lose to attacking teams? Pull 4h of DECISION logs and
profile possession height, shot ranges, and defensive siege indicators."""
import json
from collections import Counter, defaultdict

import boto3

from analyze_match import find_log_groups, run_query

logs = boto3.session.Session().client("logs", region_name="us-east-1")
groups = find_log_groups(logs, "agg_")
rows = run_query(logs, groups, 240)
print(f"rows: {len(rows)} from {len(groups)} groups\n")

by_pos = defaultdict(list)
for r in rows:
    by_pos[r.get("pos", "?")].append(r)

for pos in ("GK", "DEF", "MID", "FWD1", "FWD2"):
    items = by_pos.get(pos, [])
    if not items:
        continue
    n = len(items)
    hb = [r for r in items if r.get("hb") == 1]
    dgs = sorted(r["dg"] for r in hb if isinstance(r.get("dg"), (int, float)))
    med = dgs[len(dgs)//2] if dgs else None
    in45 = sum(1 for d in dgs if d <= 45)
    shots = [r for r in items if r.get("cmd") == "SHOOT"]
    shots_far = sum(1 for r in shots if isinstance(r.get("dg"), (int, float)) and r["dg"] > 45)
    ovs = Counter(r.get("ov") for r in items if r.get("ov"))
    print(f"{pos}: ticks={n} held_ball={len(hb)} (dg min={dgs[0] if dgs else '-'} "
          f"med={med} max={dgs[-1] if dgs else '-'}) in_range_ticks={in45}")
    print(f"     shots={len(shots)} (beyond45={shots_far})  ov={dict(ovs) or '-'}")

# Field tilt proxy: forwards' distance-to-opp-goal over time = how deep we are pinned
fw = [r for r in rows if r.get("pos") in ("FWD1", "FWD2") and isinstance(r.get("dg"), (int, float))]
fw_deep = sum(1 for r in fw if r["dg"] >= 60)
print(f"\nforwards pinned deep (dg>=60): {fw_deep}/{len(fw)} = {100*fw_deep//max(len(fw),1)}%")

gk = by_pos.get("GK", [])
busy = sum(1 for r in gk if r.get("cmd") in ("INTERCEPT", "SLIDE_TACKLE", "PRESS_BALL", "CLEAR_BALL"))
print(f"GK emergency actions: {busy}/{len(gk)} ticks")

# possession share proxy: any of our players holding the ball
ticks_seen = defaultdict(int)
ticks_held = defaultdict(int)
for r in rows:
    key = (r.get("_log", ""), r.get("tick"))
for r in rows:
    t = r.get("t")
    if t is None:
        continue
    ticks_seen[t] += 1
    if r.get("hb") == 1:
        ticks_held[t] += 1
held_any = sum(1 for t in ticks_seen if ticks_held.get(t, 0) > 0)
print(f"game-seconds where ANY of us held the ball: {held_any}/{len(ticks_seen)} "
      f"= {100*held_any//max(len(ticks_seen),1)}%")
