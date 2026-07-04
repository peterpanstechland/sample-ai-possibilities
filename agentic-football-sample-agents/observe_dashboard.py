"""Local web dashboard for match observation.

Serves a single-page frontend that polls CloudWatch (via this server) for the
per-tick DECISION lines the agents emit, and renders:
  - per-agent cards: decision sources, LLM latency p50/p95, shot count,
    command mix, tuning recommendations
  - latency-over-time scatter (all agents)
  - command distribution bars

Runs entirely on your machine with your AWS credentials — nothing to deploy.

Usage:
  python observe_dashboard.py                      # http://localhost:8777
  python observe_dashboard.py --port 9000 --prefix agg_ --minutes 60
"""

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import boto3

from analyze_match import find_log_groups, run_query, aggregate

CACHE_TTL_SECONDS = 20  # avoid hammering Logs Insights on page refreshes

_cache = {"key": None, "ts": 0.0, "payload": None}
_cache_lock = threading.Lock()


def fetch_data(region: str, prefix: str, minutes: int) -> dict:
    key = (region, prefix, minutes)
    with _cache_lock:
        if _cache["key"] == key and time.time() - _cache["ts"] < CACHE_TTL_SECONDS:
            return _cache["payload"]

    logs = boto3.client("logs", region_name=region)
    groups = find_log_groups(logs, prefix)
    rows = run_query(logs, groups, minutes) if groups else []
    payload = {
        "generated_at": time.strftime("%H:%M:%S"),
        "minutes": minutes,
        "prefix": prefix,
        "groups": len(groups),
        "agents": aggregate(rows),
        "rows": rows[-400:],  # recent points for the latency chart
    }
    with _cache_lock:
        _cache.update(key=key, ts=time.time(), payload=payload)
    return payload


PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Football Agents — Match Observability</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root { --bg:#0f1115; --card:#181b22; --line:#2a2f3a; --text:#e6e9ef;
          --dim:#9aa4b2; --accent:#4f8ef7; --good:#34c37e; --warn:#f5a623; --bad:#ef5350; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 "Segoe UI",system-ui,sans-serif; }
  header { display:flex; align-items:center; gap:16px; padding:14px 22px;
           border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); z-index:5; }
  header h1 { font-size:17px; margin:0; font-weight:600; }
  header .meta { color:var(--dim); font-size:12px; }
  header .controls { margin-left:auto; display:flex; gap:8px; align-items:center; }
  select, button { background:var(--card); color:var(--text); border:1px solid var(--line);
                   border-radius:6px; padding:5px 10px; font-size:13px; cursor:pointer; }
  main { padding:18px 22px; max-width:1500px; margin:0 auto; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(265px,1fr)); gap:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .card h2 { margin:0 0 2px; font-size:15px; display:flex; justify-content:space-between; }
  .card .rt { color:var(--dim); font-size:11px; word-break:break-all; }
  .kpis { display:flex; gap:14px; margin:10px 0 6px; flex-wrap:wrap; }
  .kpi .v { font-size:19px; font-weight:600; }
  .kpi .l { font-size:11px; color:var(--dim); }
  .srcbar { display:flex; height:8px; border-radius:4px; overflow:hidden; margin:6px 0; }
  .cmds { color:var(--dim); font-size:12px; margin-top:6px; }
  .recs { margin:8px 0 0; padding:0 0 0 16px; font-size:12px; color:var(--warn); }
  .healthy { color:var(--good); font-size:12px; margin-top:8px; }
  .charts { display:grid; grid-template-columns:2fr 1fr; gap:14px; margin-top:18px; }
  .chartbox { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; }
  .chartbox h3 { margin:2px 4px 8px; font-size:13px; color:var(--dim); font-weight:500; }
  #empty { text-align:center; color:var(--dim); padding:60px 0; }
  @media (max-width:1000px){ .charts { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>Football Agents 观测台</h1>
  <span class="meta" id="meta">loading…</span>
  <div class="controls">
    <select id="minutes">
      <option value="15">最近 15 分钟</option>
      <option value="30">最近 30 分钟</option>
      <option value="60" selected>最近 60 分钟</option>
      <option value="180">最近 3 小时</option>
    </select>
    <button id="refresh">刷新</button>
  </div>
</header>
<main>
  <div id="empty" style="display:none">暂无 DECISION 数据 — 先打一场比赛，或调大时间窗口。</div>
  <div class="cards" id="cards"></div>
  <div class="charts">
    <div class="chartbox"><h3>LLM 延迟随时间（ms，按位置着色，虚线 = 900ms 超时风险线）</h3><canvas id="latChart" height="110"></canvas></div>
    <div class="chartbox"><h3>指令分布（全队）</h3><canvas id="cmdChart" height="220"></canvas></div>
  </div>
</main>
<script>
const SRC_COLORS = { llm:"#34c37e", "parse-fallback":"#f5a623", "error-fallback":"#ef5350", "last-resort":"#b71c1c" };
const POS_COLORS = { GK:"#4f8ef7", DEF:"#34c37e", MID:"#f5a623", FWD1:"#ef5350", FWD2:"#ab47bc" };
let latChart, cmdChart;

async function load() {
  const minutes = document.getElementById("minutes").value;
  const res = await fetch(`/api/data?minutes=${minutes}`);
  const data = await res.json();
  document.getElementById("meta").textContent =
    `${data.groups} 个日志组 · 窗口 ${data.minutes} 分钟 · 更新于 ${data.generated_at}`;

  const cards = document.getElementById("cards");
  cards.innerHTML = "";
  document.getElementById("empty").style.display = data.agents.length ? "none" : "block";

  for (const a of data.agents) {
    const total = a.ticks;
    const srcbar = Object.entries(a.sources).map(([s,c]) =>
      `<div style="width:${100*c/total}%;background:${SRC_COLORS[s]||"#888"}" title="${s}: ${c}"></div>`).join("");
    const cmds = Object.entries(a.commands).map(([c,k]) => `${c}:${k}`).join("  ");
    const recs = a.recommendations.length
      ? `<ul class="recs">${a.recommendations.map(r=>`<li>${r}</li>`).join("")}</ul>`
      : `<div class="healthy">健康 — 无建议</div>`;
    cards.insertAdjacentHTML("beforeend", `
      <div class="card">
        <h2><span style="color:${POS_COLORS[a.pos]||"#fff"}">${a.pos}</span><span>${a.shots} 射门</span></h2>
        <div class="rt">${a.runtime}</div>
        <div class="kpis">
          <div class="kpi"><div class="v">${a.ticks}</div><div class="l">ticks</div></div>
          <div class="kpi"><div class="v">${Math.round(100*a.llm_ratio)}%</div><div class="l">LLM 决策</div></div>
          <div class="kpi"><div class="v">${a.latency.p50 ?? "—"}</div><div class="l">p50 ms</div></div>
          <div class="kpi"><div class="v">${a.latency.p95 ?? "—"}</div><div class="l">p95 ms</div></div>
        </div>
        <div class="srcbar">${srcbar}</div>
        <div class="cmds">${cmds}</div>
        ${recs}
      </div>`);
  }

  // latency scatter by game time
  const dsMap = {};
  for (const r of data.rows) {
    if (r.source !== "llm" || r.latency_ms == null) continue;
    (dsMap[r.pos] ??= []).push({x: r.t, y: r.latency_ms});
  }
  const scatter = Object.entries(dsMap).map(([pos,pts]) => ({
    label: pos, data: pts, backgroundColor: POS_COLORS[pos]||"#888", pointRadius: 2.5,
  }));
  latChart?.destroy();
  latChart = new Chart(document.getElementById("latChart"), {
    type: "scatter",
    data: { datasets: scatter },
    options: {
      animation:false, scales:{
        x:{ title:{display:true,text:"比赛时间 s",color:"#9aa4b2"}, grid:{color:"#2a2f3a"}, ticks:{color:"#9aa4b2"} },
        y:{ grid:{color:"#2a2f3a"}, ticks:{color:"#9aa4b2"} } },
      plugins:{ legend:{labels:{color:"#e6e9ef"}}, annotation:undefined },
    }
  });
  // 900ms guide line via dataset
  latChart.data.datasets.push({ label:"timeout risk", type:"line", borderColor:"#ef5350",
    borderDash:[6,4], borderWidth:1, pointRadius:0,
    data:[{x:0,y:900},{x:Math.max(...data.rows.map(r=>r.t||0), 60),y:900}] });
  latChart.update();

  // command bars (whole team)
  const cmdTotals = {};
  for (const a of data.agents)
    for (const [c,k] of Object.entries(a.commands)) cmdTotals[c] = (cmdTotals[c]||0)+k;
  const labels = Object.keys(cmdTotals).sort((a,b)=>cmdTotals[b]-cmdTotals[a]);
  cmdChart?.destroy();
  cmdChart = new Chart(document.getElementById("cmdChart"), {
    type: "bar",
    data: { labels, datasets: [{ data: labels.map(l=>cmdTotals[l]),
            backgroundColor: labels.map(l=>l==="SHOOT"?"#ef5350":"#4f8ef7") }] },
    options: { animation:false, indexAxis:"y",
      scales:{ x:{grid:{color:"#2a2f3a"},ticks:{color:"#9aa4b2"}},
               y:{grid:{display:false},ticks:{color:"#e6e9ef"}} },
      plugins:{ legend:{display:false} } }
  });
}

document.getElementById("refresh").onclick = load;
document.getElementById("minutes").onchange = load;
load();
setInterval(load, 30000);
</script>
</body>
</html>"""


def make_handler(region: str, prefix: str, default_minutes: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                body = PAGE.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/data":
                qs = parse_qs(url.query)
                minutes = int(qs.get("minutes", [default_minutes])[0])
                try:
                    payload = fetch_data(region, prefix, minutes)
                    body = json.dumps(payload).encode()
                    self.send_response(200)
                except Exception as e:  # surface AWS/query errors to the page
                    body = json.dumps({"error": str(e), "agents": [], "rows": [],
                                       "groups": 0, "minutes": minutes,
                                       "generated_at": time.strftime("%H:%M:%S")}).encode()
                    self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass  # keep the console quiet

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--prefix", default="agg_", help="runtime name prefix (default agg_)")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 make_handler(args.region, args.prefix, args.minutes))
    print(f"Dashboard: http://localhost:{args.port}  (prefix={args.prefix}, region={args.region})")
    server.serve_forever()


if __name__ == "__main__":
    main()
