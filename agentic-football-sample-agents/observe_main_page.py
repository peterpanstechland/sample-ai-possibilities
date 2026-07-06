"""Main observability dashboard HTML (bilingual)."""

from observe_i18n import I18N_SCRIPT, SHARED_STYLES, nav_header

MAIN_PAGE = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Football Agents — Match Observability</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root {{ --bg:#0f1115; --card:#181b22; --line:#2a2f3a; --text:#e6e9ef;
          --dim:#9aa4b2; --accent:#4f8ef7; --good:#34c37e; --warn:#f5a623; --bad:#ef5350; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 "Segoe UI",system-ui,sans-serif; }}
  header {{ display:flex; align-items:center; gap:16px; padding:14px 22px;
           border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); z-index:5; }}
  header h1 {{ font-size:17px; margin:0; font-weight:600; }}
  header .meta {{ color:var(--dim); font-size:12px; }}
  header .controls {{ margin-left:auto; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
  {SHARED_STYLES}
  select, button {{ background:var(--card); color:var(--text); border:1px solid var(--line);
                   border-radius:6px; padding:5px 10px; font-size:13px; cursor:pointer; }}
  main {{ padding:18px 22px; max-width:1500px; margin:0 auto; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(265px,1fr)); gap:14px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card h2 {{ margin:0 0 2px; font-size:15px; display:flex; justify-content:space-between; }}
  .card .rt {{ color:var(--dim); font-size:11px; word-break:break-all; }}
  .kpis {{ display:flex; gap:14px; margin:10px 0 6px; flex-wrap:wrap; }}
  .kpi .v {{ font-size:19px; font-weight:600; }}
  .kpi .l {{ font-size:11px; color:var(--dim); }}
  .srcbar {{ display:flex; height:8px; border-radius:4px; overflow:hidden; margin:6px 0; }}
  .cmds {{ color:var(--dim); font-size:12px; margin-top:6px; }}
  .recs {{ margin:8px 0 0; padding:0 0 0 16px; font-size:12px; color:var(--warn); }}
  .healthy {{ color:var(--good); font-size:12px; margin-top:8px; }}
  .charts {{ display:grid; grid-template-columns:2fr 1fr; gap:14px; margin-top:18px; }}
  .chartbox {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; }}
  .chartbox h3 {{ margin:2px 4px 8px; font-size:13px; color:var(--dim); font-weight:500; }}
  #empty {{ text-align:center; color:var(--dim); padding:60px 0; }}
  table.cmp {{ width:100%; border-collapse:collapse; font-size:13px; margin-top:6px; }}
  table.cmp th, table.cmp td {{ padding:4px 8px; text-align:right; border-bottom:1px solid var(--line); }}
  table.cmp th:first-child, table.cmp td:first-child {{ text-align:left; }}
  table.cmp th {{ color:var(--dim); font-weight:500; font-size:12px; }}
  .delta-bad {{ color:var(--bad); font-weight:600; }}
  .tag {{ font-size:11px; color:var(--dim); }}
  @media (max-width:1000px){{ .charts {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<header>
  <h1 data-i18n="dash.title"></h1>
  {nav_header("observability")}
  <span class="meta" id="meta" data-i18n="common.loading"></span>
  <div class="controls">
    <select id="source">
      <option value="cloud" selected data-i18n="dash.source.cloud"></option>
      <option value="local" data-i18n="dash.source.local"></option>
      <option value="both" data-i18n="dash.source.both"></option>
    </select>
    <select id="minutes">
      <option value="15" data-i18n="dash.minutes.15"></option>
      <option value="30" data-i18n="dash.minutes.30"></option>
      <option value="60" selected data-i18n="dash.minutes.60"></option>
      <option value="180" data-i18n="dash.minutes.180"></option>
    </select>
    <button id="refresh" data-i18n="common.refresh"></button>
  </div>
</header>
<main>
  <div id="empty" style="display:none" data-i18n="dash.empty"></div>
  <div class="cards" id="cards"></div>
  <div class="charts" id="charts">
    <div class="chartbox" id="latBox"><h3 id="latTitle" data-i18n="dash.lat_chart"></h3><canvas id="latChart" height="110"></canvas></div>
    <div class="chartbox"><h3 id="cmdTitle" data-i18n="dash.cmd_chart"></h3><canvas id="cmdChart" height="220"></canvas></div>
  </div>
</main>
<script>
{I18N_SCRIPT}
const SRC_COLORS = {{ llm:"#34c37e", fallback:"#4f8ef7", "parse-fallback":"#f5a623", "error-fallback":"#ef5350", "last-resort":"#b71c1c" }};
const POS_COLORS = {{ GK:"#4f8ef7", DEF:"#34c37e", MID:"#f5a623", FWD1:"#ef5350", FWD2:"#ab47bc" }};
const POS_ORDER = ["GK","DEF","MID","FWD1","FWD2"];
let latChart, cmdChart;

function agentCard(a) {{
  const total = a.ticks;
  const srcbar = Object.entries(a.sources).map(([s,c]) =>
    `<div style="width:${{100*c/total}}%;background:${{SRC_COLORS[s]||"#888"}}" title="${{s}}: ${{c}}"></div>`).join("");
  const cmds = Object.entries(a.commands).map(([c,k]) => `${{c}}:${{k}}`).join("  ");
  const recs = a.recommendations.length
    ? `<ul class="recs">${{a.recommendations.map(r=>`<li>${{r}}</li>`).join("")}}</ul>`
    : `<div class="healthy">${{t("dash.healthy")}}</div>`;
  const disc = a.discipline && a.discipline.chances
    ? `<div class="kpi"><div class="v">${{a.discipline.shots}}/${{a.discipline.chances}}</div><div class="l">${{t("dash.shot_discipline")}}</div></div>` : "";
  const ovTotal = a.overrides ? Object.values(a.overrides).reduce((s,v)=>s+v,0) : 0;
  const ov = ovTotal
    ? `<div class="kpi" title="${{Object.entries(a.overrides).map(([k,v])=>`${{k}}:${{v}}`).join("  ")}}"><div class="v">${{ovTotal}}</div><div class="l">${{t("dash.override_fixes")}}</div></div>` : "";
  return `
    <div class="card">
      <h2><span style="color:${{POS_COLORS[a.pos]||"#fff"}}">${{a.pos}}</span><span>${{a.shots}} ${{t("common.shots")}}</span></h2>
      <div class="rt">${{a.runtime}}</div>
      <div class="kpis">
        <div class="kpi"><div class="v">${{a.ticks}}</div><div class="l">${{t("common.ticks")}}</div></div>
        <div class="kpi"><div class="v">${{Math.round(100*a.llm_ratio)}}%</div><div class="l">${{t("dash.llm_decisions")}}</div></div>
        <div class="kpi"><div class="v">${{a.latency.p50 ?? "—"}}</div><div class="l">p50 ms</div></div>
        <div class="kpi"><div class="v">${{a.latency.p95 ?? "—"}}</div><div class="l">p95 ms</div></div>
        ${{disc}}${{ov}}
      </div>
      <div class="srcbar">${{srcbar}}</div>
      <div class="cmds">${{cmds}}</div>
      ${{recs}}
    </div>`;
}}

function pct(n, d) {{ return d ? Math.round(100*n/d) : 0; }}

function compareCard(pos, c, l) {{
  const row = (name, cv, lv, markBigDelta) => {{
    let cls = "";
    if (markBigDelta && cv != null && lv != null && Math.abs(cv - lv) >= 15) cls = "delta-bad";
    return `<tr><td>${{name}}</td><td>${{cv ?? "—"}}</td><td>${{lv ?? "—"}}</td>
            <td class="${{cls}}">${{cv != null && lv != null ? (cv - lv > 0 ? "+" : "") + (cv - lv) : "—"}}</td></tr>`;
  }};
  const shootC = c ? pct(c.shots, c.ticks) : null, shootL = l ? pct(l.shots, l.ticks) : null;
  const moveC = c ? pct(c.commands.MOVE_TO||0, c.ticks) : null, moveL = l ? pct(l.commands.MOVE_TO||0, l.ticks) : null;
  const discC = c?.discipline?.chances ? pct(c.discipline.shots, c.discipline.chances) : null;
  const discL = l?.discipline?.chances ? pct(l.discipline.shots, l.discipline.chances) : null;
  return `
    <div class="card">
      <h2><span style="color:${{POS_COLORS[pos]||"#fff"}}">${{pos}}</span>
          <span class="tag">${{t("dash.live_vs_train")}}</span></h2>
      <table class="cmp">
        <tr><th></th><th>${{t("dash.live")}}</th><th>${{t("dash.train")}}</th><th>Δ</th></tr>
        ${{row(t("common.ticks"), c?.ticks, l?.ticks, false)}}
        ${{row(t("dash.shoot_pct"), shootC, shootL, true)}}
        ${{row(t("dash.discipline_pct"), discC, discL, true)}}
        ${{row(t("dash.move_pct"), moveC, moveL, true)}}
        ${{row(t("dash.llm_pct"), c ? Math.round(100*c.llm_ratio) : null, l ? Math.round(100*l.llm_ratio) : null, false)}}
        ${{row("p50 ms", c?.latency.p50, l?.latency.p50, false)}}
        ${{row("p95 ms", c?.latency.p95, l?.latency.p95, false)}}
      </table>
      ${{shootC != null && shootL != null && shootL - shootC >= 15
        ? `<ul class="recs"><li>${{t("dash.compare_hint", {{n: shootL - shootC}})}}</li></ul>` : ""}}
    </div>`;
}}

function cmdTotals(agents) {{
  const tot = {{}};
  for (const a of agents) for (const [c,k] of Object.entries(a.commands)) tot[c] = (tot[c]||0)+k;
  return tot;
}}

function renderSingle(data) {{
  document.getElementById("cards").innerHTML = data.agents.map(agentCard).join("");
  document.getElementById("empty").style.display = data.agents.length ? "none" : "block";
  document.getElementById("latBox").style.display = "";
  document.getElementById("cmdTitle").textContent = t("dash.cmd_chart");

  const dsMap = {{}};
  for (const r of data.rows) {{
    if (r.source !== "llm" || r.latency_ms == null) continue;
    (dsMap[r.pos] ??= []).push({{x: r.t, y: r.latency_ms}});
  }}
  const scatter = Object.entries(dsMap).map(([pos,pts]) => ({{
    label: pos, data: pts, backgroundColor: POS_COLORS[pos]||"#888", pointRadius: 2.5,
  }}));
  latChart?.destroy();
  latChart = new Chart(document.getElementById("latChart"), {{
    type: "scatter",
    data: {{ datasets: scatter }},
    options: {{ animation:false, scales:{{
        x:{{ title:{{display:true,text:t("dash.time_axis"),color:"#9aa4b2"}}, grid:{{color:"#2a2f3a"}}, ticks:{{color:"#9aa4b2"}} }},
        y:{{ grid:{{color:"#2a2f3a"}}, ticks:{{color:"#9aa4b2"}} }} }},
      plugins:{{ legend:{{labels:{{color:"#e6e9ef"}}}} }} }}
  }});
  latChart.data.datasets.push({{ label:"timeout risk", type:"line", borderColor:"#ef5350",
    borderDash:[6,4], borderWidth:1, pointRadius:0,
    data:[{{x:0,y:900}},{{x:Math.max(...data.rows.map(r=>r.t||0), 60),y:900}}] }});
  latChart.update();

  const totals = cmdTotals(data.agents);
  const labels = Object.keys(totals).sort((a,b)=>totals[b]-totals[a]);
  cmdChart?.destroy();
  cmdChart = new Chart(document.getElementById("cmdChart"), {{
    type: "bar",
    data: {{ labels, datasets: [{{ data: labels.map(x=>totals[x]),
            backgroundColor: labels.map(x=>x==="SHOOT"?"#ef5350":"#4f8ef7") }}] }},
    options: {{ animation:false, indexAxis:"y",
      scales:{{ x:{{grid:{{color:"#2a2f3a"}},ticks:{{color:"#9aa4b2"}}}},
               y:{{grid:{{display:false}},ticks:{{color:"#e6e9ef"}}}} }},
      plugins:{{ legend:{{display:false}} }} }}
  }});
}}

function renderCompare(cloud, local) {{
  const byPos = src => Object.fromEntries(src.agents.map(a=>[a.pos, a]));
  const c = byPos(cloud), l = byPos(local);
  const poses = POS_ORDER.filter(p => c[p] || l[p]);
  document.getElementById("cards").innerHTML = poses.map(p => compareCard(p, c[p], l[p])).join("");
  document.getElementById("empty").style.display = poses.length ? "none" : "block";
  document.getElementById("latBox").style.display = "none";
  latChart?.destroy(); latChart = null;
  document.getElementById("cmdTitle").textContent = t("dash.cmd_compare");
  const ct = cmdTotals(cloud.agents), lt = cmdTotals(local.agents);
  const cn = cloud.agents.reduce((s,a)=>s+a.ticks,0), ln = local.agents.reduce((s,a)=>s+a.ticks,0);
  const labels = [...new Set([...Object.keys(ct), ...Object.keys(lt)])]
    .sort((a,b)=>(ct[b]||0)+(lt[b]||0)-(ct[a]||0)-(lt[a]||0));
  cmdChart?.destroy();
  cmdChart = new Chart(document.getElementById("cmdChart"), {{
    type: "bar",
    data: {{ labels, datasets: [
      {{ label:t("dash.live"), data: labels.map(x=>pct(ct[x]||0, cn)), backgroundColor:"#4f8ef7" }},
      {{ label:t("dash.train"), data: labels.map(x=>pct(lt[x]||0, ln)), backgroundColor:"#34c37e" }},
    ]}},
    options: {{ animation:false, indexAxis:"y",
      scales:{{ x:{{grid:{{color:"#2a2f3a"}},ticks:{{color:"#9aa4b2",callback:v=>v+"%"}}}},
               y:{{grid:{{display:false}},ticks:{{color:"#e6e9ef"}}}} }},
      plugins:{{ legend:{{labels:{{color:"#e6e9ef"}}}} }} }}
  }});
}}

function showError(msg) {{
  document.getElementById("meta").textContent = t("common.error");
  const empty = document.getElementById("empty");
  empty.style.display = "block";
  empty.style.color = "var(--bad)";
  empty.textContent = "⚠ " + msg;
  document.getElementById("cards").innerHTML = "";
}}

async function load(syncCloud=false) {{
  const source = document.getElementById("source").value;
  const minutes = document.getElementById("minutes").value;
  document.getElementById("minutes").style.display = source === "local" ? "none" : "";
  const sync = (syncCloud && source !== "local") ? "&sync=1" : "";
  const res = await fetch(`/api/data?source=${{source}}&minutes=${{minutes}}${{sync}}`);
  const data = await res.json();
  if (data.error) {{
    showError(data.error_key ? t(data.error_key) : data.error);
    return;
  }}
  document.getElementById("empty").style.color = "";
  if (source === "both") {{
    document.getElementById("meta").textContent =
      `${{data.cloud.label}} ↔ ${{data.local.label}} · ${{t("common.updated")}} ${{data.generated_at}}`;
    renderCompare(data.cloud, data.local);
  }} else {{
    const d = source === "local" ? data.local : data.cloud;
    document.getElementById("meta").textContent = `${{d.label}} · ${{t("common.updated")}} ${{data.generated_at}}`;
    renderSingle(d);
  }}
}}

document.getElementById("refresh").onclick = () => load(true);
document.getElementById("minutes").onchange = () => load(false);
document.getElementById("source").onchange = () => load(false);
function onLangChanged() {{ load(false); }}
applyI18n();
load(false);
setInterval(() => load(false), 30000);
</script>
</body>
</html>"""
