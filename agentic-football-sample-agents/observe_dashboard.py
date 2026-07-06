"""Local web dashboard for match observation.

Serves a single-page frontend with three data sources:
  - 实战 (cloud):   per-tick DECISION lines the deployed agents emit to CloudWatch
  - 训练场 (local): JSONL runs produced by training_ground.py
  - 对比 (compare): cloud vs training side by side — spot where real-match
    behavior diverges from the training ground before changing strategy

Per agent: decision sources, LLM latency p50/p95, shot count, command mix,
tuning recommendations; plus latency-over-time and command distribution charts.

Runs entirely on your machine with your AWS credentials — nothing to deploy.

Usage:
  python observe_dashboard.py                      # http://localhost:8777
  python observe_dashboard.py --port 9000 --prefix agg_ --minutes 60
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO / "lib"))

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from analyze_match import find_log_groups, run_query, aggregate
from aws_clients import aws_client
from cloudwatch_store import append_decisions, load_decisions, merge_decisions, store_stats
from aws_credentials import (
    credentials_status,
    test_credentials_payload,
    write_credentials,
    write_region,
)
from match_analytics import build_analytics_payload, advise_players
from observe_analytics import ANALYTICS_PAGE
from observe_main_page import MAIN_PAGE
from observe_settings import SETTINGS_PAGE

CACHE_TTL_SECONDS = 20  # avoid hammering Logs Insights on page refreshes
TRAINING_DIR = Path(__file__).parent / "training_logs"

_cache = {}
_cache_lock = threading.Lock()

# STS error codes that mean "credentials are dead", not "query is broken"
_AUTH_ERROR_CODES = {
    "ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId",
    "UnrecognizedClientException", "AccessDeniedException", "AccessDenied",
}


class AuthError(RuntimeError):
    """AWS credentials missing or expired."""


def _auth_error() -> AuthError:
    return AuthError("auth")


def _clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _logs_client(region: str):
    """Prefer ~/.aws/credentials over process env vars."""
    return aws_client("logs", region, use_proxy=False)


def _cached(key, fn):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (time.time(), val)
    return val


def _fetch_decision_rows(region: str, prefix: str, minutes: int,
                         *, sync_cloud: bool = True) -> tuple[list[dict], dict]:
    """Load DECISION rows. sync_cloud=False uses cloudwatch_logs/ only (fast path)."""
    local_rows = load_decisions(prefix, minutes)
    if not sync_cloud:
        if local_rows:
            st = store_stats(prefix)
            return local_rows, {
                "groups": 0, "source": "local_cache", "saved_new": 0,
                "rows_merged": len(local_rows), **st,
            }
        sync_cloud = True  # no local data — must query CloudWatch

    try:
        logs = _logs_client(region)
        groups = find_log_groups(logs, prefix)
        cloud_rows = run_query(logs, groups, minutes) if groups else []
    except NoCredentialsError:
        local = load_decisions(prefix, minutes)
        if local:
            st = store_stats(prefix)
            return local, {
                "groups": 0, "source": "local", "saved_new": 0,
                "rows_merged": len(local), **st,
            }
        raise _auth_error()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in _AUTH_ERROR_CODES:
            local = load_decisions(prefix, minutes)
            if local:
                st = store_stats(prefix)
                return local, {
                    "groups": 0, "source": "local", "saved_new": 0,
                    "rows_merged": len(local), **st,
                }
            raise _auth_error()
        raise
    except BotoCoreError as e:
        local = load_decisions(prefix, minutes)
        if local:
            st = store_stats(prefix)
            return local, {
                "groups": 0, "source": "local", "saved_new": 0,
                "rows_merged": len(local), **st,
            }
        raise RuntimeError(f"AWS error: {e}") from e

    saved = append_decisions(prefix, cloud_rows)
    local_rows = load_decisions(prefix, minutes)
    merged = merge_decisions(local_rows, cloud_rows)
    st = store_stats(prefix)
    return merged, {
        "groups": len(groups),
        "source": "cloud",
        "saved_new": saved,
        "rows_cloud": len(cloud_rows),
        "rows_merged": len(merged),
        **st,
    }


def fetch_cloud(region: str, prefix: str, minutes: int,
                *, sync_cloud: bool = True) -> dict:
    def load():
        rows, meta = _fetch_decision_rows(region, prefix, minutes, sync_cloud=sync_cloud)
        saved = meta.get("saved_new", 0)
        src = meta.get("source", "cloud")
        label = (f"实战 · {meta.get('groups', 0)} 个日志组 · 最近 {minutes} 分钟"
                 f" · 本地 {meta.get('rows', 0)} 条")
        if saved:
            label += f" (+{saved} 新保存)"
        if src == "local_cache":
            label += " · 本地缓存"
        elif src == "local":
            label += " · 离线缓存"
        return {"label": label, "agents": aggregate(rows), "rows": rows[-400:],
                "local_store": meta}
    return _cached(("cloud", region, prefix, minutes, sync_cloud), load)


def fetch_local() -> dict:
    def load():
        files = sorted(TRAINING_DIR.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
        if not files:
            return {"label": "训练场 · 暂无数据（先运行 training_ground.py）",
                    "agents": [], "rows": []}
        latest = files[-1]
        rows = []
        with open(latest, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return {"label": f"训练场 · {latest.name} · {len(rows)} 条",
                "agents": aggregate(rows), "rows": rows[-400:]}
    return _cached(("local",), load)


def _error_payload(exc: Exception) -> tuple[dict, int]:
    if isinstance(exc, AuthError):
        return {"error_key": "error.auth", "error": "auth"}, 500
    return {"error": str(exc)}, 500


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e


def _send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_html(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_jsonl_download(handler: BaseHTTPRequestHandler, rows: list[dict],
                         filename: str, meta: dict) -> None:
    lines = [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows]
    body = ("\n".join(lines) + "\n" if lines else "").encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Rows-Total", str(len(rows)))
    handler.send_header("X-Rows-Cloud", str(meta.get("rows_cloud", 0)))
    handler.send_header("X-Rows-Saved", str(meta.get("saved_new", 0)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def fetch_analytics(region: str, prefix: str, minutes: int,
                    match: str | None = None, *, sync_cloud: bool = True) -> dict:
    def load():
        rows, meta = _fetch_decision_rows(region, prefix, minutes, sync_cloud=sync_cloud)
        payload = build_analytics_payload(rows, match=match)
        payload["generated_at"] = time.strftime("%H:%M:%S")
        src = meta.get("source", "cloud")
        label = (f"实战 · {meta.get('groups', 0)} 组 · {minutes} 分钟"
                   f" · 本地 {meta.get('rows', 0)} 条")
        if src == "local_cache":
            label += " · 本地缓存"
        elif src == "local":
            label += " · 离线缓存"
        payload["label"] = label
        payload["local_store"] = meta
        return payload
    return _cached(("analytics", region, prefix, minutes, match or "all", sync_cloud), load)


def make_handler(region: str, prefix: str, default_minutes: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            try:
                if url.path == "/":
                    _send_html(self, MAIN_PAGE)
                elif url.path == "/analytics":
                    _send_html(self, ANALYTICS_PAGE)
                elif url.path == "/settings":
                    _send_html(self, SETTINGS_PAGE)
                elif url.path == "/api/settings/aws":
                    st = credentials_status(region=region)
                    _send_json(self, st)
                elif url.path == "/api/cloud/store":
                    qs = parse_qs(url.query)
                    pfx = qs.get("prefix", [prefix])[0]
                    _send_json(self, store_stats(pfx))
                elif url.path == "/api/settings/cloudwatch/download":
                    qs = parse_qs(url.query)
                    minutes = int(qs.get("minutes", [default_minutes])[0])
                    pfx = qs.get("prefix", [prefix])[0]
                    _clear_cache()
                    rows, meta = _fetch_decision_rows(region, pfx, minutes)
                    fname = f"{pfx}decisions_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
                    _send_jsonl_download(self, rows, fname, meta)
                elif url.path == "/api/analytics":
                    qs = parse_qs(url.query)
                    minutes = int(qs.get("minutes", [default_minutes])[0])
                    match = qs.get("match", [None])[0]
                    sync = qs.get("sync", ["0"])[0] in ("1", "true", "yes")
                    payload = fetch_analytics(region, prefix, minutes, match=match,
                                              sync_cloud=sync)
                    _send_json(self, payload)
                elif url.path == "/api/advise":
                    qs = parse_qs(url.query)
                    minutes = int(qs.get("minutes", [default_minutes])[0])
                    model = qs.get("model", [None])[0]
                    match = qs.get("match", [None])[0]
                    sync = qs.get("sync", ["0"])[0] in ("1", "true", "yes")
                    payload = fetch_analytics(region, prefix, minutes, match=match,
                                              sync_cloud=sync)
                    advice = advise_players(payload, region=region, model_id=model)
                    _send_json(self, advice)
                elif url.path == "/api/data":
                    qs = parse_qs(url.query)
                    minutes = int(qs.get("minutes", [default_minutes])[0])
                    source = qs.get("source", ["cloud"])[0]
                    sync = qs.get("sync", ["0"])[0] in ("1", "true", "yes")
                    payload = {"generated_at": time.strftime("%H:%M:%S")}
                    if source in ("cloud", "both"):
                        payload["cloud"] = fetch_cloud(region, prefix, minutes,
                                                       sync_cloud=sync)
                    if source in ("local", "both"):
                        payload["local"] = fetch_local()
                    _send_json(self, payload)
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception as e:
                err, code = _error_payload(e)
                _send_json(self, err, code)

        def do_POST(self):
            url = urlparse(self.path)
            try:
                data = _read_json_body(self)
                if url.path == "/api/settings/aws":
                    profile = (data.get("profile") or "default").strip()
                    key_id = (data.get("access_key_id") or "").strip()
                    secret = (data.get("secret_access_key") or "").strip()
                    token = data.get("session_token")
                    reg = (data.get("region") or region).strip()
                    if not key_id or not secret:
                        _send_json(self, {"error": "missing_keys"}, 400)
                        return
                    write_credentials(
                        access_key_id=key_id,
                        secret_access_key=secret,
                        session_token=token,
                        profile=profile,
                    )
                    if reg:
                        write_region(reg, profile=profile)
                    _clear_cache()
                    st = credentials_status(profile=profile, region=reg)
                    _send_json(self, {"ok": True, "status": st})
                elif url.path == "/api/settings/aws/test":
                    result = test_credentials_payload(
                        access_key_id=data.get("access_key_id", ""),
                        secret_access_key=data.get("secret_access_key", ""),
                        session_token=data.get("session_token"),
                        region=(data.get("region") or region).strip(),
                    )
                    _send_json(self, result, 200 if result.get("valid") else 400)
                else:
                    self.send_response(404)
                    self.end_headers()
            except ValueError as e:
                _send_json(self, {"error": str(e)}, 400)
            except Exception as e:
                err, code = _error_payload(e)
                _send_json(self, err, code)

        def log_message(self, fmt, *args):
            pass

    return Handler


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--prefix", default="agg_", help="runtime name prefix (default agg_)")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    args = ap.parse_args()

    server = _Server(("127.0.0.1", args.port),
                     make_handler(args.region, args.prefix, args.minutes))
    print(f"Dashboard: http://localhost:{args.port}  (prefix={args.prefix}, region={args.region})",
          flush=True)
    print(f"Analytics: http://localhost:{args.port}/analytics", flush=True)
    print(f"Settings:  http://localhost:{args.port}/settings", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

