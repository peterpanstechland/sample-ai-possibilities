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
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://agentic-football.aws.dev"
API_BASE = "https://l3fmtx4zp0.execute-api.us-east-1.amazonaws.com/prod"
PROFILE_DIR = Path(__file__).parent / ".portal-profile"
TOKEN_KEY = "world_cup_team_token"
SESSION_KEY = "world_cup_team_session"
CODE_ENV = "AAFC_TEAM_CODE"            # pin the team code without a browser
CODE_FILE = PROFILE_DIR / "team_code.txt"  # gitignored (inside .portal-profile)


def _normalize_code(code: str | None) -> str | None:
    """Accept 'team:XX1234', 'XX1234', or whitespace-padded input."""
    if not code:
        return None
    code = code.strip()
    if code.lower().startswith("team:"):
        code = code[5:]
    return code or None


def _resolve_saved_code() -> str | None:
    """The pinned team code: env var wins, else the saved file."""
    code = _normalize_code(os.environ.get(CODE_ENV))
    if code:
        return code
    try:
        return _normalize_code(CODE_FILE.read_text(encoding="utf-8"))
    except OSError:
        return None

BOTS = {
    "balanced": "The Benchmark FC",
    "aggressive": "Total Attack United",
    "defensive": "Fort Knox Athletic",
}


class PortalError(RuntimeError):
    pass


class PortalBot:
    """One persistent-profile Chromium context around the player portal."""

    def __init__(self, headed: bool = False, base_url: str = BASE_URL,
                 cdp_url: str | None = None):
        self.base_url = base_url
        self.headed = headed
        self.cdp_url = cdp_url          # attach to a real browser over CDP
        self._pw = None
        self._browser = None
        self._ctx = None
        self.page = None

    # --- lifecycle -----------------------------------------------------------
    def __enter__(self):
        self._pw = sync_playwright().start()
        if self.cdp_url:
            self._attach_over_cdp()
        else:
            PROFILE_DIR.mkdir(exist_ok=True)
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=not self.headed,
                viewport={"width": 1440, "height": 900},
                # The portal's CDN edge sometimes serves a cert Chromium flags
                # as ERR_CERT_COMMON_NAME_INVALID (Python/OpenSSL accepts the
                # same host). Team-code auth, automation-only session.
                ignore_https_errors=True,
            )
            self.page = (self._ctx.pages[0] if self._ctx.pages
                         else self._ctx.new_page())
        return self

    def _attach_over_cdp(self):
        """Connect to a Chrome/Edge already running with --remote-debugging-port.
        Reuses that browser's profile: the portal login is right there."""
        # On Windows 'localhost' often resolves to IPv6 ::1, but Chrome's debug
        # port listens on IPv4 127.0.0.1 -> use the explicit IPv4 loopback.
        url = self.cdp_url.replace("//localhost:", "//127.0.0.1:")
        try:
            self._browser = self._pw.chromium.connect_over_cdp(url)
        except Exception as e:
            raise PortalError(
                f"Could not attach to a browser at {url}: {e}\n"
                "Start Chrome/Edge with a debug port AND a DEDICATED profile "
                "dir (Chrome 136+ ignores the debug port on the default "
                "profile), e.g. in PowerShell:\n"
                '  & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                '--remote-debugging-port=9222 --user-data-dir="$env:TEMP\\aafc-debug"\n'
                "The pinned team code authenticates it, so no manual login "
                "is needed in that window.")
        self._ctx = (self._browser.contexts[0] if self._browser.contexts
                     else self._browser.new_context())
        # Prefer a tab already on the portal; otherwise reuse/open one.
        for pg in self._ctx.pages:
            if BASE_URL.split("//")[-1] in (pg.url or ""):
                self.page = pg
                break
        else:
            self.page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def __exit__(self, *exc):
        try:
            if self.cdp_url:
                if self._browser:      # detach only — never close the user's browser
                    self._browser.close()
            else:
                self._ctx.close()
        finally:
            self._pw.stop()

    # --- auth ----------------------------------------------------------------
    def _local_storage(self, key: str) -> str | None:
        return self.page.evaluate("k => localStorage.getItem(k)", key)

    def _browser_token(self) -> str | None:
        """Login state of THIS browser profile — localStorage only, no pinned
        fallback. Used to tell whether the visible SPA is actually logged in."""
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

    def token(self) -> str | None:
        # 1) whatever the SPA stored in this profile's localStorage; else
        # 2) fall back to the pinned team code (env/file) — the portal's auth
        #    is just "Bearer team:<CODE>", so this is the same identity the
        #    browser uses. Survives a wiped/locked profile or a fresh machine.
        tok = self._browser_token()
        if tok:
            return tok
        code = _resolve_saved_code()
        return f"team:{code}" if code else None

    def _login_with_code(self, code: str):
        """Log the current browser in through the portal UI (type code + Join)
        so the SPA stores its full session and the window shows the team — not
        just the code-entry screen. Falls back to seeding localStorage."""
        try:
            box = self.page.get_by_placeholder("ENTER TEAM CODE")
            box.wait_for(timeout=8000)
            box.fill(code)
            self.page.get_by_role("button", name="Join").click()
            try:
                self.page.wait_for_url("**/player**", timeout=20_000)
            except PWTimeout:
                pass  # _browser_token() below is the source of truth
            self.page.wait_for_timeout(1500)
        except Exception:
            # No visible login form — seed the token and reload so the SPA
            # re-initializes from localStorage on next load.
            try:
                self.page.evaluate("([k, v]) => localStorage.setItem(k, v)",
                                    [TOKEN_KEY, f"team:{code}"])
                self.page.reload(wait_until="domcontentloaded")
                self.page.wait_for_timeout(1500)
            except Exception:
                pass  # API calls still work off the pinned code

    def _on_portal(self) -> bool:
        return BASE_URL.split("//")[-1] in (self.page.url or "")

    def ensure_login(self, team_code: str | None = None,
                     interactive_wait_s: int = 300) -> dict:
        """Return my team dict; join with the team code first if needed."""
        # When attached to the user's real browser, don't hijack a tab they're
        # watching — only navigate if we're not already on the portal origin
        # (localStorage is per-origin, so we must be on the portal to read it).
        if not (self.cdp_url and self._on_portal()):
            self.page.goto(self.base_url, wait_until="domcontentloaded")
            self.page.wait_for_timeout(1500)

        code = _normalize_code(team_code) or _resolve_saved_code()

        # If this browser profile isn't logged in yet but we have a code, log
        # it in FOR REAL via the UI. (Checking _browser_token, not token(), so
        # the pinned-code fallback doesn't mask an un-logged-in browser.)
        if not self._browser_token() and code:
            self._login_with_code(code)
            CODE_FILE.parent.mkdir(exist_ok=True)
            try:
                CODE_FILE.write_text(code, encoding="utf-8")
            except OSError:
                pass

        if not self.token() and self.headed:
            print(f"Waiting up to {interactive_wait_s}s — enter your TEAM CODE "
                  f"in the browser window...")
            deadline = time.time() + interactive_wait_s
            while time.time() < deadline and not self.token():
                self.page.wait_for_timeout(2000)

        if not self.token():
            raise PortalError(
                "No portal session. Run: python portal_bot.py setup --team-code "
                f"<CODE>  (or set {CODE_ENV}=<CODE>)")

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
                        capacity_retries: int = 8,
                        capacity_wait_s: int = 60) -> str:
        """POST /practice-matches; retries while the arena is at capacity or
        while the previous practice slot is still being released (the backend
        keeps the slot 'in progress' for a few minutes after full time)."""
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
                retryable = ("CAPACITY" in s.upper() or "429" in s or "409" in s
                             or "practice match in progress" in s.lower())
                if retryable:
                    print(f"  slot busy ({attempt + 1}/{capacity_retries}), "
                          f"retrying in {capacity_wait_s}s...")
                    time.sleep(capacity_wait_s)
                    continue
                raise
        raise PortalError("Practice slot stayed busy — try again later.")

    def open_viewer(self, match_id: str):
        """Open the live viewer tab. Also nudges client-side match plumbing
        (agent health checks) the same way a human player would."""
        try:
            self.page.goto(f"{self.base_url}/v2/player/matches/{match_id}/viewer",
                           wait_until="domcontentloaded")
        except PWTimeout:
            pass

    def wait_for_result(self, match_id: str, my_team_id: str,
                        timeout_s: int = 1500, poll_s: int = 10,
                        coach: "LiveCoach | None" = None) -> dict:
        """Poll the match until completed/cancelled; return the normalized
        record plus my side / my score / opponent score / won flag.
        A LiveCoach, when given, reads live events on every poll and shouts
        situational COACH ORDERs into the team chat."""
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
            if coach is not None and m["status"] == "in_progress":
                try:
                    coach.poll(self._attach_sides(dict(m), my_team_id)["my_side"])
                except Exception as e:  # coaching is best-effort, never fatal
                    print(f"  coach poll error (non-fatal): {e}")
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

    def narration(self, match_id: str, since: int = 0) -> dict:
        """Incremental live events: momentType (buildup/pressing/shot/goal/
        final_whistle), teamSide, params.{home,away} score on goals, gameTime."""
        return self.api("GET", f"/matches/{match_id}/narration?since={since}")

    def match_report(self, match_id: str) -> dict:
        try:
            return self.api("GET", f"/matches/{match_id}/report")
        except PortalError as e:
            return {"error": str(e)}

    def recent_matches(self, team_id: str | None = None) -> list[dict]:
        path = (f"/matches?team_id={team_id}&limit=100" if team_id
                else "/matches")
        out = self.api("GET", path)
        items = sorted(out.get("items", []),
                       key=lambda m: m.get("created_at") or "", reverse=True)
        return [self._norm_match(m) for m in items]

    def find_live_match(self, team_id: str) -> dict | None:
        """Newest starting/in-progress match involving our team, if any."""
        for m in self.recent_matches(team_id):
            if m["status"] in ("starting", "in_progress"):
                return m
        return None


class LiveCoach:
    """Situational touchline coach: reads the live narration feed and sends
    coach instructions the game engine forwards into every agent's prompt as
    a top-priority COACH ORDER (lib/state.py) — one well-timed order steers
    all five LLMs at once.

    The portal only accepts preset instructions (free text is rejected with
    400), so situations map onto the 6 presets. Event-driven (react to goals
    immediately) + state-driven (score/time phase), with a cooldown and
    same-situation dedupe so the chat isn't flooded.
    """

    MATCH_LEN = 120  # gameTime runs 0..120 in portal matches
    PRESETS = ("press_high", "play_possession", "shoot_on_sight",
               "slow_the_tempo", "increase_the_tempo", "go_all_out_attack")

    def __init__(self, bot: PortalBot, match_id: str, team_id: str,
                 cooldown_s: float = 45.0):
        self.bot = bot
        self.match_id = match_id
        self.team_id = team_id
        self.cooldown_s = cooldown_s
        self._since = 0
        self._last_sent_at = 0.0
        self._last_key = None
        self.my = 0
        self.opp = 0
        self.game_time = 0
        self._opp_threats: list[int] = []  # gameTimes of opp shots/pressing

    # --- situation -> preset instruction --------------------------------------
    def _decide(self, scored: bool, conceded: bool) -> tuple[str, str] | None:
        """Return (situation, preset). The engine turns presets into touchline
        shouts, e.g. shoot_on_sight -> 'Why are you keeping the ball! Shoot!'"""
        diff = self.my - self.opp
        late = self.game_time >= self.MATCH_LEN * 0.7
        siege = (sum(1 for t in self._opp_threats
                     if t >= self.game_time - 30) >= 3)

        if conceded:
            return ("conceded", "press_high")            # win the ball back now
        if scored and diff > 0:
            return ("scored", "slow_the_tempo")          # keep the shape, no chaos
        if diff < 0 and late:
            return ("chase-late", "go_all_out_attack")   # nothing to lose
        if diff < 0:
            return ("chase", "shoot_on_sight")           # our identity: shoot more
        if diff > 0 and late:
            return ("protect", "slow_the_tempo")         # hold the line
        if diff == 0 and late:
            return ("push-late", "increase_the_tempo")   # go win it
        if siege and diff <= 0:
            return ("siege", "slow_the_tempo")           # compact, then counter
        return None

    def poll(self, my_side: str):
        """Ingest new narration events, then send at most one instruction."""
        n = self.bot.narration(self.match_id, since=self._since)
        if isinstance(n.get("latestSeq"), int):
            self._since = max(self._since, n["latestSeq"])
        scored = conceded = False
        for ev in n.get("lines") or []:
            t = ev.get("gameTime") or 0
            self.game_time = max(self.game_time, t)
            mt, side = ev.get("momentType"), ev.get("teamSide")
            if mt == "goal":
                p = ev.get("params") or {}
                if isinstance(p.get("home"), int) and isinstance(p.get("away"), int):
                    self.my, self.opp = ((p["home"], p["away"])
                                         if my_side == "home"
                                         else (p["away"], p["home"]))
                if side == my_side:
                    scored = True
                else:
                    conceded = True
            elif mt in ("shot", "pressing") and side and side != my_side:
                self._opp_threats.append(t)

        decision = self._decide(scored, conceded)
        if decision is None:
            return
        key, preset = decision
        urgent = key in ("conceded", "scored")  # goals bypass the cooldown
        now = time.time()
        if not urgent and now - self._last_sent_at < self.cooldown_s:
            return
        if preset == self._last_key:
            return  # already the active order — repeating it adds nothing
        try:
            self.bot.send_coach_order(self.match_id, self.team_id, preset)
        except PortalError as e:
            if "in-progress" in str(e):
                return  # final whistle beat us to it — benign race
            raise
        self._last_sent_at, self._last_key = now, preset
        print(f"  COACH [{self.game_time}s {self.my}-{self.opp}] {key} -> {preset}")


# --- CLI ----------------------------------------------------------------------

def _add_cdp_args(p):
    p.add_argument("--cdp", nargs="?", const="http://127.0.0.1:9222",
                   metavar="URL",
                   help="attach to YOUR running browser over CDP "
                        "(default http://127.0.0.1:9222). Start Chrome/Edge "
                        "with --remote-debugging-port=9222 AND a dedicated "
                        "--user-data-dir first.")


def _cdp_url(args) -> str | None:
    return getattr(args, "cdp", None)


def cmd_setup(args):
    code = _normalize_code(args.team_code)
    if code:  # pin it so every future run reuses this exact team identity
        CODE_FILE.parent.mkdir(exist_ok=True)
        CODE_FILE.write_text(code, encoding="utf-8")
    # Headless works when we already have a code to pin; only pop a browser
    # when we need the user to type the code in interactively.
    with PortalBot(headed=not code) as bot:
        team = bot.ensure_login(code)
        print(f"Logged in: {team.get('team_name') or team.get('name')} "
              f"(team_id={team['team_id']})")
        print(f"Team code pinned to {CODE_FILE} and seeded into "
              f".portal-profile/ — all runs reuse this session.")


def cmd_status(args):
    with PortalBot(headed=args.headed, cdp_url=_cdp_url(args)) as bot:
        team = bot.ensure_login()
        print(f"Team: {team.get('team_name') or team.get('name')} "
              f"(team_id={team['team_id']})")
        for m in bot.recent_matches(team["team_id"])[:8]:
            score = (f"{m['home_score']}-{m['away_score']}"
                     if m["home_score"] is not None else "—")
            print(f"  [{m['status']:>11}] {m['home_name']} vs {m['away_name']} "
                  f"{score} ({'practice' if m['is_practice'] else 'event'})")


def cmd_match(args):
    result = play_one_match(bot_variant=args.bot, headed=args.headed,
                            coach_order=args.coach, timeout_s=args.timeout,
                            live_coach=not args.no_live_coach)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("won") else 1)


def cmd_report(args):
    with PortalBot(headed=args.headed) as bot:
        bot.ensure_login()
        print(json.dumps(bot.match_report(args.match_id), indent=2,
                         ensure_ascii=False))


def cmd_coach(args):
    """Attach the situational LiveCoach to a running match. Start it BEFORE
    kickoff with --wait: it stands by and takes over the moment a match goes
    live. --forever keeps coaching every subsequent match. --cdp attaches to
    your own already-open browser instead of the bot's profile."""
    wait = args.wait or args.forever
    cdp = _cdp_url(args)
    with PortalBot(headed=args.headed, cdp_url=cdp) as bot:
        if cdp:
            print(f"attached to your browser at {cdp}")
        team = bot.ensure_login()
        team_id = team["team_id"]
        wins = losses = 0
        seen: set[str] = set()  # don't re-coach a match the list API still shows live

        def next_live():
            m = bot.find_live_match(team_id)
            return None if (m and m["id"] in seen) else m

        while True:
            if args.match:
                m = bot._norm_match(bot.api("GET", f"/matches/{args.match}"))
            else:
                m = next_live()
                if m is None:
                    if not wait:
                        print("No live match found — start with --wait to "
                              "stand by for kickoff.")
                        sys.exit(2)
                    print("standby: waiting for kickoff (Ctrl+C to stop)...")
                    while m is None:
                        time.sleep(10)
                        m = next_live()
            seen.add(m["id"])
            print(f"Coaching {m['home_name']} vs {m['away_name']} "
                  f"(match {m['id']}, status {m['status']})...")
            coach = LiveCoach(bot, m["id"], team_id, cooldown_s=args.cooldown)
            result = bot.wait_for_result(m["id"], team_id,
                                         timeout_s=args.timeout, coach=coach)
            result["coach_final"] = {"my": coach.my, "opp": coach.opp,
                                     "last_order": coach._last_key}
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if not args.forever or args.match:
                sys.exit(0 if result.get("won") else 1)
            wins, losses = wins + bool(result.get("won")), \
                losses + (not result.get("won"))
            print(f"— record this session: {wins}W {losses}L —")


def play_one_match(bot_variant: str = "aggressive", headed: bool = False,
                   coach_order: str | None = None,
                   timeout_s: int = 1500, live_coach: bool = True) -> dict:
    """One full portal round-trip (login -> match vs bot -> final score).
    This is the entry point autopilot.py uses. live_coach=True keeps a
    situational touchline coach shouting COACH ORDERs during the match."""
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
        coach = (LiveCoach(bot, match_id, team_id) if live_coach else None)
        result = bot.wait_for_result(match_id, team_id, timeout_s=timeout_s,
                                     coach=coach)
        result["report"] = bot.match_report(match_id)
        result["bot"] = bot_variant
        result["duration_s"] = round(time.time() - t0)
        if coach is not None:
            result["coach_final"] = {"my": coach.my, "opp": coach.opp,
                                     "last_key": coach._last_key}
        return result


def main():
    sys.stdout.reconfigure(line_buffering=True)  # live progress when piped
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="interactive login, saves the session")
    p.add_argument("--team-code", help="team code to join with")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("status", help="session + recent matches")
    p.add_argument("--headed", action="store_true")
    _add_cdp_args(p)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("match", help="play one practice match vs a bot")
    p.add_argument("--bot", choices=sorted(BOTS), default="aggressive")
    p.add_argument("--coach", help="coach order to send at kickoff")
    p.add_argument("--no-live-coach", action="store_true",
                   help="disable the situational touchline coach")
    p.add_argument("--timeout", type=int, default=1500,
                   help="max seconds to wait for the final whistle")
    p.add_argument("--headed", action="store_true", help="watch the match live")
    p.set_defaults(fn=cmd_match)

    p = sub.add_parser("report", help="fetch a match report")
    p.add_argument("--match-id", required=True)
    p.add_argument("--headed", action="store_true")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("coach", help="live-coach the current in-progress match")
    p.add_argument("--match", help="match id (default: newest live match)")
    p.add_argument("--wait", action="store_true",
                   help="start before the match: stand by until kickoff")
    p.add_argument("--forever", action="store_true",
                   help="keep standing by and coach every match (implies --wait)")
    p.add_argument("--cooldown", type=float, default=30.0,
                   help="min seconds between non-urgent orders")
    p.add_argument("--timeout", type=int, default=1500)
    p.add_argument("--headed", action="store_true")
    _add_cdp_args(p)
    p.set_defaults(fn=cmd_coach)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
