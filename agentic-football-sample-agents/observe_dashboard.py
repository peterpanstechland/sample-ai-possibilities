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
import configparser
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from analyze_match import find_log_groups, run_query, aggregate

CACHE_TTL_SECONDS = 20  # avoid hammering Logs Insights on page refreshes
TRAINING_DIR = Path(__file__).parent / "training_logs"

_cache = {}
_cache_lock = threading.Lock()

# STS error codes that mean "credentials are dead", not "query is broken"
_AUTH_ERROR_CODES = {
    "ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId",
    "UnrecognizedClientException", "AccessDeniedException", "AccessDenied",
}
_AUTH_HINT = ("AWS 凭证过期/无效（session 失效）。请从 Workshop Studio 重新获取凭证并更新 "
              "~/.aws/credentials（运行 aws configure 或直接编辑文件），刷新本页即可。"
              "若仍报错，检查启动 dashboard 的终端是否还 export 了旧的 AWS_* 环境变量，"
              "关闭该终端或重启 observe_dashboard.py。")


def _logs_client(region: str):
    """Prefer ~/.aws/credentials over process env vars.

    Workshop flows often update the file while an old terminal still exports
    expired AWS_ACCESS_KEY_ID / AWS_SESSION_TOKEN — boto3 would keep using those.
    """
    cred_path = Path.home() / ".aws" / "credentials"
    if cred_path.exists():
        cp = configparser.ConfigParser()
        cp.read(cred_path)
        if cp.has_section("default"):
            section = cp["default"]
            key_id = section.get("aws_access_key_id")
            if key_id:
                return boto3.session.Session(
                    aws_access_key_id=key_id,
                    aws_secret_access_key=section.get("aws_secret_access_key"),
                    aws_session_token=section.get("aws_session_token"),
                    region_name=region,
                ).client("logs")
    return boto3.session.Session().client("logs", region_name=region)


def _cached(key, fn):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (time.time(), val)
    return val


def fetch_cloud(region: str, prefix: str, minutes: int) -> dict:
    def load():
        try:
            logs = _logs_client(region)
            groups = find_log_groups(logs, prefix)
            rows = run_query(logs, groups, minutes) if groups else []
        except NoCredentialsError:
            raise RuntimeError(_AUTH_HINT)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in _AUTH_ERROR_CODES:
                raise RuntimeError(_AUTH_HINT)
            raise
        except BotoCoreError as e:
            raise RuntimeError(f"AWS 调用失败: {e}")
        return {"label": f"实战 · {len(groups)} 个日志组 · 最近 {minutes} 分钟",
                "agents": aggregate(rows), "rows": rows[-400:]}
    return _cached(("cloud", region, prefix, minutes), load)


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
  /* compare view */
  table.cmp { width:100%; border-collapse:collapse; font-size:13px; margin-top:6px; }
  table.cmp th, table.cmp td { padding:4px 8px; text-align:right; border-bottom:1px solid var(--line); }
  table.cmp th:first-child, table.cmp td:first-child { text-align:left; }
  table.cmp th { color:var(--dim); font-weight:500; font-size:12px; }
  .delta-bad { color:var(--bad); font-weight:600; }
  .delta-ok { color:var(--good); }
  .tag { font-size:11px; color:var(--dim); }
  @media (max-width:1000px){ .charts { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>Football Agents 观测台</h1>
  <span class="meta" id="meta">loading…</span>
  <div class="controls">
    <select id="source">
      <option value="cloud" selected>实战 (CloudWatch)</option>
      <option value="local">训练场 (本地)</option>
      <option value="both">对比：实战 vs 训练</option>
    </select>
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
  <div id="empty" style="display:none">暂无数据 — 实战：先打一场比赛或调大时间窗口；训练场：先运行 training_ground.py。</div>
  <div class="cards" id="cards"></div>
  <div class="charts" id="charts">
    <div class="chartbox" id="latBox"><h3>LLM 延迟随时间（ms，按位置着色，虚线 = 900ms 超时风险线）</h3><canvas id="latChart" height="110"></canvas></div>
    <div class="chartbox"><h3 id="cmdTitle">指令分布（全队）</h3><canvas id="cmdChart" height="220"></canvas></div>
  </div>
</main>
<script>
const SRC_COLORS = { llm:"#34c37e", fallback:"#4f8ef7", "parse-fallback":"#f5a623", "error-fallback":"#ef5350", "last-resort":"#b71c1c" };
const POS_COLORS = { GK:"#4f8ef7", DEF:"#34c37e", MID:"#f5a623", FWD1:"#ef5350", FWD2:"#ab47bc" };
const POS_ORDER = ["GK","DEF","MID","FWD1","FWD2"];
let latChart, cmdChart;

function agentCard(a) {
  const total = a.ticks;
  const srcbar = Object.entries(a.sources).map(([s,c]) =>
    `<div style="width:${100*c/total}%;background:${SRC_COLORS[s]||"#888"}" title="${s}: ${c}"></div>`).join("");
  const cmds = Object.entries(a.commands).map(([c,k]) => `${c}:${k}`).join("  ");
  const recs = a.recommendations.length
    ? `<ul class="recs">${a.recommendations.map(r=>`<li>${r}</li>`).join("")}</ul>`
    : `<div class="healthy">健康 — 无建议</div>`;
  const disc = a.discipline && a.discipline.chances
    ? `<div class="kpi"><div class="v">${a.discipline.shots}/${a.discipline.chances}</div><div class="l">把握射门</div></div>` : "";
  const ovTotal = a.overrides ? Object.values(a.overrides).reduce((s,v)=>s+v,0) : 0;
  const ov = ovTotal
    ? `<div class="kpi" title="${Object.entries(a.overrides).map(([k,v])=>`${k}:${v}`).join("  ")}"><div class="v">${ovTotal}</div><div class="l">代码纠偏</div></div>` : "";
  return `
    <div class="card">
      <h2><span style="color:${POS_COLORS[a.pos]||"#fff"}">${a.pos}</span><span>${a.shots} 射门</span></h2>
      <div class="rt">${a.runtime}</div>
      <div class="kpis">
        <div class="kpi"><div class="v">${a.ticks}</div><div class="l">ticks</div></div>
        <div class="kpi"><div class="v">${Math.round(100*a.llm_ratio)}%</div><div class="l">LLM 决策</div></div>
        <div class="kpi"><div class="v">${a.latency.p50 ?? "—"}</div><div class="l">p50 ms</div></div>
        <div class="kpi"><div class="v">${a.latency.p95 ?? "—"}</div><div class="l">p95 ms</div></div>
        ${disc}${ov}
      </div>
      <div class="srcbar">${srcbar}</div>
      <div class="cmds">${cmds}</div>
      ${recs}
    </div>`;
}

function pct(n, d) { return d ? Math.round(100*n/d) : 0; }

function compareCard(pos, c, l) {
  // c = cloud agent stats, l = local training agent stats (either may be null)
  const row = (name, cv, lv, markBigDelta) => {
    let cls = "";
    if (markBigDelta && cv != null && lv != null && Math.abs(cv - lv) >= 15) cls = "delta-bad";
    return `<tr><td>${name}</td><td>${cv ?? "—"}</td><td>${lv ?? "—"}</td>
            <td class="${cls}">${cv != null && lv != null ? (cv - lv > 0 ? "+" : "") + (cv - lv) : "—"}</td></tr>`;
  };
  const shootC = c ? pct(c.shots, c.ticks) : null, shootL = l ? pct(l.shots, l.ticks) : null;
  const moveC = c ? pct(c.commands.MOVE_TO||0, c.ticks) : null, moveL = l ? pct(l.commands.MOVE_TO||0, l.ticks) : null;
  const discC = c?.discipline?.chances ? pct(c.discipline.shots, c.discipline.chances) : null;
  const discL = l?.discipline?.chances ? pct(l.discipline.shots, l.discipline.chances) : null;
  return `
    <div class="card">
      <h2><span style="color:${POS_COLORS[pos]||"#fff"}">${pos}</span>
          <span class="tag">实战 vs 训练</span></h2>
      <table class="cmp">
        <tr><th></th><th>实战</th><th>训练</th><th>Δ</th></tr>
        ${row("ticks", c?.ticks, l?.ticks, false)}
        ${row("射门 %", shootC, shootL, true)}
        ${row("把握射门 %", discC, discL, true)}
        ${row("MOVE_TO %", moveC, moveL, true)}
        ${row("LLM %", c ? Math.round(100*c.llm_ratio) : null, l ? Math.round(100*l.llm_ratio) : null, false)}
        ${row("p50 ms", c?.latency.p50, l?.latency.p50, false)}
        ${row("p95 ms", c?.latency.p95, l?.latency.p95, false)}
      </table>
      ${shootC != null && shootL != null && shootL - shootC >= 15
        ? `<ul class="recs"><li>实战射门率比训练低 ${shootL - shootC} 个百分点 — 检查实战状态注入（hasBall/TACTICS）或对手压迫下的决策</li></ul>` : ""}
    </div>`;
}

function cmdTotals(agents) {
  const t = {};
  for (const a of agents) for (const [c,k] of Object.entries(a.commands)) t[c] = (t[c]||0)+k;
  return t;
}

function renderSingle(data) {
  const cards = document.getElementById("cards");
  cards.innerHTML = data.agents.map(agentCard).join("");
  document.getElementById("empty").style.display = data.agents.length ? "none" : "block";
  document.getElementById("latBox").style.display = "";
  document.getElementById("cmdTitle").textContent = "指令分布（全队）";

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
    options: { animation:false, scales:{
        x:{ title:{display:true,text:"比赛/训练时间 s",color:"#9aa4b2"}, grid:{color:"#2a2f3a"}, ticks:{color:"#9aa4b2"} },
        y:{ grid:{color:"#2a2f3a"}, ticks:{color:"#9aa4b2"} } },
      plugins:{ legend:{labels:{color:"#e6e9ef"}} } }
  });
  latChart.data.datasets.push({ label:"timeout risk", type:"line", borderColor:"#ef5350",
    borderDash:[6,4], borderWidth:1, pointRadius:0,
    data:[{x:0,y:900},{x:Math.max(...data.rows.map(r=>r.t||0), 60),y:900}] });
  latChart.update();

  const totals = cmdTotals(data.agents);
  const labels = Object.keys(totals).sort((a,b)=>totals[b]-totals[a]);
  cmdChart?.destroy();
  cmdChart = new Chart(document.getElementById("cmdChart"), {
    type: "bar",
    data: { labels, datasets: [{ data: labels.map(x=>totals[x]),
            backgroundColor: labels.map(x=>x==="SHOOT"?"#ef5350":"#4f8ef7") }] },
    options: { animation:false, indexAxis:"y",
      scales:{ x:{grid:{color:"#2a2f3a"},ticks:{color:"#9aa4b2"}},
               y:{grid:{display:false},ticks:{color:"#e6e9ef"}} },
      plugins:{ legend:{display:false} } }
  });
}

function renderCompare(cloud, local) {
  const byPos = src => Object.fromEntries(src.agents.map(a=>[a.pos, a]));
  const c = byPos(cloud), l = byPos(local);
  const poses = POS_ORDER.filter(p => c[p] || l[p]);
  const cards = document.getElementById("cards");
  cards.innerHTML = poses.map(p => compareCard(p, c[p], l[p])).join("");
  document.getElementById("empty").style.display = poses.length ? "none" : "block";

  // hide latency scatter; show grouped command distribution (% of ticks)
  document.getElementById("latBox").style.display = "none";
  latChart?.destroy(); latChart = null;
  document.getElementById("cmdTitle").textContent = "指令分布对比（占各自总 tick 的 %）";
  const ct = cmdTotals(cloud.agents), lt = cmdTotals(local.agents);
  const cn = cloud.agents.reduce((s,a)=>s+a.ticks,0), ln = local.agents.reduce((s,a)=>s+a.ticks,0);
  const labels = [...new Set([...Object.keys(ct), ...Object.keys(lt)])]
    .sort((a,b)=>(ct[b]||0)+(lt[b]||0)-(ct[a]||0)-(lt[a]||0));
  cmdChart?.destroy();
  cmdChart = new Chart(document.getElementById("cmdChart"), {
    type: "bar",
    data: { labels, datasets: [
      { label:"实战", data: labels.map(x=>pct(ct[x]||0, cn)), backgroundColor:"#4f8ef7" },
      { label:"训练", data: labels.map(x=>pct(lt[x]||0, ln)), backgroundColor:"#34c37e" },
    ]},
    options: { animation:false, indexAxis:"y",
      scales:{ x:{grid:{color:"#2a2f3a"},ticks:{color:"#9aa4b2",callback:v=>v+"%"}},
               y:{grid:{display:false},ticks:{color:"#e6e9ef"}} },
      plugins:{ legend:{labels:{color:"#e6e9ef"}} } }
  });
}

async function load() {
  const source = document.getElementById("source").value;
  const minutes = document.getElementById("minutes").value;
  document.getElementById("minutes").style.display = source === "local" ? "none" : "";
  const res = await fetch(`/api/data?source=${source}&minutes=${minutes}`);
  const data = await res.json();
  if (data.error) {
    document.getElementById("meta").textContent = "查询出错";
    const empty = document.getElementById("empty");
    empty.style.display = "block";
    empty.style.color = "var(--bad)";
    empty.textContent = `⚠ ${data.error}`;
    document.getElementById("cards").innerHTML = "";
    return;
  }
  document.getElementById("empty").style.color = "";
  if (source === "both") {
    document.getElementById("meta").textContent =
      `${data.cloud.label} ↔ ${data.local.label} · 更新于 ${data.generated_at}`;
    renderCompare(data.cloud, data.local);
  } else {
    const d = source === "local" ? data.local : data.cloud;
    document.getElementById("meta").textContent = `${d.label} · 更新于 ${data.generated_at}`;
    renderSingle(d);
  }
}

document.getElementById("refresh").onclick = load;
document.getElementById("minutes").onchange = load;
document.getElementById("source").onchange = load;
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
                source = qs.get("source", ["cloud"])[0]
                try:
                    payload = {"generated_at": time.strftime("%H:%M:%S")}
                    if source in ("cloud", "both"):
                        payload["cloud"] = fetch_cloud(region, prefix, minutes)
                    if source in ("local", "both"):
                        payload["local"] = fetch_local()
                    body = json.dumps(payload, ensure_ascii=False).encode()
                    self.send_response(200)
                except Exception as e:  # surface AWS/query errors to the page
                    body = json.dumps({"error": str(e)}, ensure_ascii=False).encode()
                    self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass  # keep the console quiet

    return Handler


class _Server(ThreadingHTTPServer):
    # On Windows allow_reuse_address lets a second instance silently bind the
    # same port and race for connections — fail loudly instead.
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
    server.serve_forever()


if __name__ == "__main__":
    main()
