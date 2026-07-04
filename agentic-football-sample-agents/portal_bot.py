"""Playwright driver for the AAFC Player Portal (https://agentic-football.aws.dev).

Automates the human part of an iteration loop: join with the team code, start a
practice match against a bot, watch it in the real match viewer, wait for the
final whistle and return the score. autopilot.py builds the full
match -> analyze -> tune -> redeploy cycle on top of this.

How it talks to the portal (mapped from the production JS bundle):
  POST {API}/teams/login            {"team_code": ...}     -> session JSON
  GET  {API}/teams/mine                                    -> my team (id, event)
  POST {API}/practice-matches       {"team_id", "opponent"} -> {"match_id"}
       opponent in {"balanced", "aggressive", "defensive"}
       (portal names: The Benchmark FC / Total Attack United / Fort Knox Athletic)
  GET  {API}/matches/{id}                                  -> status + result
  GET  {API}/matches/{id}/report                           -> post-match stats
  POST {API}/matches/{id}/coach-instructions {"team_id", "instruction"}
  Auth: "Authorization: Bearer <world_cup_team_token>" (a "team:<code>" string
  minted by the login call and kept in localStorage by the SPA).

The browser session (team join) persists in .portal-profile/, so interactive
login is a one-time step:

  python portal_bot.py setup --team-code ABC123        # or omit to type it in
  python portal_bot.py match --bot aggressive          # play one bot match
  python portal_bot.py match --bot aggressive --headed # ...and watch it live
  python portal_bot.py status                          # session + recent matches
  python portal_bot.py report --match-id <id>          # final score + stats
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://agentic-football.aws.dev"
API_BASE = "https://l3fmtx4zp0.execute-api.us-east-1.amazonaws.com/prod"
PROFILE_DIR = Path(__file__).parent / ".portal-profile"
TOKEN_KEY = "world_cup_team_token"
SESSION_KEY = "world_cup_team_session"

BOTS = {
    "balanced": "The Benchmark FC",
    "aggressive": "Total Attack United",
    "defensive": "Fort Knox Athletic",
}


class PortalError(RuntimeError):
    pass


class PortalBot:
    """One persistent-profile Chromium context around the player portal."""

    def __init__(self, headed: bool = False, base_url: str = BASE_URL):
        self.base_url = base_url
        self.headed = headed
        self._pw = None
        self._ctx = None
        self.page = None

    # --- lifecycle -----------------------------------------------------------
    def __enter__(self):
        self._pw = sync_playwright().start()
        PROFILE_DIR.mkdir(exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=not self.headed,
            viewport={"width": 1440, "height": 900},
        )
        self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            self._ctx.close()
        finally:
            self._pw.stop()

    # --- auth ----------------------------------------------------------------
    def _local_storage(self, key: str) -> str | None:
        return self.page.evaluate("k => localStorage.getItem(k)", key)

    def token(self) -> str | None:
        tok = self._local_storage(TOKEN_KEY)
        if tok:
            return tok
        raw = self._local_storage(SESSION_KEY)
        if raw:
            try:
                code = (json.loads(raw) or {}).get("team_code")
                if code:
                    return f"team:{code}"
            except json.JSONDecodeError:
                pass
        return None

    def ensure_login(self, team_code: str | None = None,
                     interactive_wait_s: int = 300) -> dict:
        """Return my team dict; join with the team code first if needed."""
        self.page.goto(self.base_url, wait_until="domcontentloaded")
        self.page.wait_for_timeout(1500)

        if not self.token() and team_code:
            box = self.page.get_by_placeholder("ENTER TEAM CODE")
            box.fill(team_code)
            self.page.get_by_role("button", name="Join").click()
            try:
                self.page.wait_for_url("**/player**", timeout=20_000)
            except PWTimeout:
                pass  # token check below is the source of truth
            self.page.wait_for_timeout(1500)

        if not self.token() and self.headed:
            print(f"Waiting up to {interactive_wait_s}s — enter your TEAM CODE "
                  f"in the browser window...")
            deadline = time.time() + interactive_wait_s
            while time.time() < deadline and not self.token():
                self.page.wait_for_timeout(2000)

        if not self.token():
            raise PortalError(
                "No portal session. Run: python portal_bot.py setup --team-code <CODE>")

        team = self.api("GET", "/teams/mine")
        if isinstance(team.get("items"), list):  # endpoint wraps the team in items[]
            team = team["items"][0] if team["items"] else {}
        if not team or not (team.get("team_id") or team.get("id")):
            raise PortalError(f"/teams/mine returned no team: {team}")
        team["team_id"] = team.get("team_id") or team.get("id")
        return team

    # --- REST through the browser's network stack ----------------------------
    def api(self, method: str, path: str, body: dict | None = None,
            timeout_ms: int = 45_000) -> dict:
        """Call the portal API with the session bearer token.

        Uses the Playwright request context (browser TLS + headers), so it
        behaves exactly like the SPA's own fetches.
        """
        tok = self.token()
        if not tok:
            raise PortalError("Not logged in (no team token in localStorage).")
        resp = self._ctx.request.fetch(
            f"{API_BASE}{path}",
            method=method,
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json"},
            data=json.dumps(body) if body is not None else None,
            timeout=timeout_ms,
        )
        text = resp.text()
        if not resp.ok:
            raise PortalError(f"{method} {path} -> {resp.status}: {text[:300]}")
        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError:
            raise PortalError(f"{method} {path} returned non-JSON: {text[:300]}")

    # --- match workflow ------------------------------------------------------
    @staticmethod
    def _norm_match(m: dict) -> dict:
        """Mirror the SPA's normalizer: snake_case/result.* -> flat fields."""
        result = m.get("result") or {}
        return {
            "id": m.get("id") or m.get("MatchId") or m.get("match_id"),
            "status": m.get("status", "pending"),
            "home_team_id": m.get("home_team_id") or m.get("homeTeamId"),
            "away_team_id": m.get("away_team_id") or m.get("awayTeamId"),
            "home_name": m.get("home_team_name") or m.get("homeTeamName"),
            "away_name": m.get("away_team_name") or m.get("awayTeamName"),
            "home_score": result.get("home_score", m.get("home_score", m.get("homeScore"))),
            "away_score": result.get("away_score", m.get("away_score", m.get("awayScore"))),
            "winner_team_id": m.get("winner_team_id") or result.get("winner_team_id"),
            "is_practice": bool(m.get("is_practice")),
        }

    def start_bot_match(self, team_id: str, bot: str,
                        capacity_retries: int = 6,
                        capacity_wait_s: int = 60) -> str:
        """POST /practice-matches; retries while the arena is at capacity."""
        if bot not in BOTS:
            raise PortalError(f"Unknown bot '{bot}' (choose from {list(BOTS)})")
        for attempt in range(capacity_retries):
            try:
                out = self.api("POST", "/practice-matches",
                               {"team_id": team_id, "opponent": bot})
                match_id = out.get("match_id") or out.get("id")
                if not match_id:
                    raise PortalError(f"practice match response had no id: {out}")
                return match_id
            except PortalError as e:
                s = str(e)
                if "CAPACITY" in s.upper() or "429" in s or "409" in s:
                    print(f"  arena busy ({attempt + 1}/{capacity_retries}), "
                          f"retrying in {capacity_wait_s}s...")
                    time.sleep(capacity_wait_s)
                    continue
                raise
        raise PortalError("Arena stayed at capacity — try again later.")

    def open_viewer(self, match_id: str):
        """Open the live viewer tab. Also nudges client-side match plumbing
        (agent health checks) the same way a human player would."""
        try:
            self.page.goto(f"{self.base_url}/v2/player/matches/{match_id}/viewer",
                           wait_until="domcontentloaded")
        except PWTimeout:
            pass

    def wait_for_result(self, match_id: str, my_team_id: str,
                        timeout_s: int = 1500, poll_s: int = 15) -> dict:
        """Poll the match until completed/cancelled; return the normalized
        record plus my side / my score / opponent score / won flag."""
        deadline = time.time() + timeout_s
        last_status = None
        while time.time() < deadline:
            try:
                m = self._norm_match(self.api("GET", f"/matches/{match_id}"))
            except PortalError as e:
                if "404" in str(e):  # eventual consistency right after creation
                    time.sleep(poll_s)
                    continue
                raise
            if m["status"] != last_status:
                print(f"  match {match_id}: {m['status']}")
                last_status = m["status"]
            if m["status"] in ("completed", "cancelled", "declined"):
                return self._attach_sides(m, my_team_id)
            time.sleep(poll_s)
        raise PortalError(f"match {match_id} did not finish within {timeout_s}s "
                          f"(last status: {last_status})")

    @staticmethod
    def _attach_sides(m: dict, my_team_id: str) -> dict:
        mine_home = str(m.get("home_team_id")) == str(my_team_id)
        my_score, opp_score = ((m.get("home_score"), m.get("away_score"))
                               if mine_home else
                               (m.get("away_score"), m.get("home_score")))
        m.update({
            "my_side": "home" if mine_home else "away",
            "my_score": my_score,
            "opp_score": opp_score,
            "won": (isinstance(my_score, (int, float))
                    and isinstance(opp_score, (int, float))
                    and my_score > opp_score),
            "opp_name": m.get("away_name") if mine_home else m.get("home_name"),
        })
        return m

    def send_coach_order(self, match_id: str, team_id: str, instruction: str):
        self.api("POST", f"/matches/{match_id}/coach-instructions",
                 {"team_id": team_id, "instruction": instruction})

    def match_report(self, match_id: str) -> dict:
        try:
            return self.api("GET", f"/matches/{match_id}/report")
        except PortalError as e:
            return {"error": str(e)}

    def recent_matches(self) -> list[dict]:
        out = self.api("GET", "/matches")
        return [self._norm_match(m) for m in out.get("items", [])]


# --- CLI ----------------------------------------------------------------------

def cmd_setup(args):
    with PortalBot(headed=True) as bot:
        team = bot.ensure_login(args.team_code)
        print(f"Logged in: {team.get('team_name') or team.get('name')} "
              f"(team_id={team['team_id']})")
        print("Session saved to .portal-profile/ — headless runs will reuse it.")


def cmd_status(args):
    with PortalBot(headed=args.headed) as bot:
        team = bot.ensure_login()
        print(f"Team: {team.get('team_name') or team.get('name')} "
              f"(team_id={team['team_id']})")
        for m in bot.recent_matches()[:8]:
            score = (f"{m['home_score']}-{m['away_score']}"
                     if m["home_score"] is not None else "—")
            print(f"  [{m['status']:>11}] {m['home_name']} vs {m['away_name']} "
                  f"{score} ({'practice' if m['is_practice'] else 'event'})")


def cmd_match(args):
    result = play_one_match(bot_variant=args.bot, headed=args.headed,
                            coach_order=args.coach, timeout_s=args.timeout)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("won") else 1)


def cmd_report(args):
    with PortalBot(headed=args.headed) as bot:
        bot.ensure_login()
        print(json.dumps(bot.match_report(args.match_id), indent=2,
                         ensure_ascii=False))


def play_one_match(bot_variant: str = "aggressive", headed: bool = False,
                   coach_order: str | None = None,
                   timeout_s: int = 1500) -> dict:
    """One full portal round-trip (login -> match vs bot -> final score).
    This is the entry point autopilot.py uses."""
    t0 = time.time()
    with PortalBot(headed=headed) as bot:
        team = bot.ensure_login()
        team_id = team["team_id"]
        print(f"Team {team.get('team_name') or team_id} vs {BOTS[bot_variant]} "
              f"({bot_variant})...")
        match_id = bot.start_bot_match(team_id, bot_variant)
        print(f"  practice match created: {match_id}")
        bot.open_viewer(match_id)
        if coach_order:
            try:
                bot.send_coach_order(match_id, team_id, coach_order)
                print(f"  coach order sent: {coach_order}")
            except PortalError as e:
                print(f"  coach order failed (non-fatal): {e}")
        result = bot.wait_for_result(match_id, team_id, timeout_s=timeout_s)
        result["report"] = bot.match_report(match_id)
        result["bot"] = bot_variant
        result["duration_s"] = round(time.time() - t0)
        return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="interactive login, saves the session")
    p.add_argument("--team-code", help="team code to join with")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("status", help="session + recent matches")
    p.add_argument("--headed", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("match", help="play one practice match vs a bot")
    p.add_argument("--bot", choices=sorted(BOTS), default="aggressive")
    p.add_argument("--coach", help="coach order to send at kickoff")
    p.add_argument("--timeout", type=int, default=1500,
                   help="max seconds to wait for the final whistle")
    p.add_argument("--headed", action="store_true", help="watch the match live")
    p.set_defaults(fn=cmd_match)

    p = sub.add_parser("report", help="fetch a match report")
    p.add_argument("--match-id", required=True)
    p.add_argument("--headed", action="store_true")
    p.set_defaults(fn=cmd_report)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
