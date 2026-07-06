"""Analytics dashboard page (football-style match analysis, bilingual)."""

from observe_i18n import I18N_SCRIPT, SHARED_STYLES, nav_header

ANALYTICS_PAGE = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Match Analytics — Football Agents</title>
<style>
  :root {{ --bg:#0a1628; --pitch:#1a4d2e; --line:#3d8b5f; --card:#121c2e; --border:#243049;
          --text:#e8edf5; --dim:#8fa3bf; --accent:#4f8ef7; --good:#34c37e; --warn:#f5a623; --bad:#ef5350; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,sans-serif; }}
  header {{ display:flex; align-items:center; gap:14px; padding:12px 20px; border-bottom:1px solid var(--border);
           position:sticky; top:0; background:var(--bg); z-index:10; flex-wrap:wrap; }}
  header h1 {{ margin:0; font-size:16px; }}
  {SHARED_STYLES}
  .controls {{ margin-left:auto; display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }}
  .controls select#advisorModel {{ max-width:220px; font-size:12px; }}
  select, button {{ background:var(--card); color:var(--text); border:1px solid var(--border);
                   border-radius:6px; padding:6px 10px; cursor:pointer; }}
  main {{ padding:16px 20px; max-width:1600px; margin:0 auto; }}
  .grid {{ display:grid; grid-template-columns:1fr 380px; gap:16px; }}
  @media(max-width:1100px){{ .grid {{ grid-template-columns:1fr; }} }}
  .panel {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:14px; }}
  .panel h2 {{ margin:0 0 10px; font-size:14px; color:var(--dim); font-weight:600; }}
  .pos-tabs {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px; }}
  .pos-tabs button {{ border-radius:20px; padding:4px 12px; font-size:12px; }}
  .pos-tabs button.active {{ background:var(--accent); border-color:var(--accent); }}
  .pitch-wrap {{ width:100%; max-width:880px; background:#121c2e;
                border-radius:8px; overflow:hidden; border:1px solid var(--border); }}
  canvas#pitch {{ width:100%; height:100%; display:block; }}
  .legend {{ font-size:11px; color:var(--dim); margin-top:6px; }}
  .stats dl {{ display:grid; grid-template-columns:1fr auto; gap:4px 12px; margin:0; font-size:13px; }}
  .stats dt {{ color:var(--dim); }}
  .stats dd {{ margin:0; text-align:right; }}
  .bar {{ height:6px; background:#243049; border-radius:3px; margin:4px 0 8px; overflow:hidden; }}
  .bar i {{ display:block; height:100%; background:var(--accent); }}
  .advice {{ margin-top:12px; padding:10px; background:#0f1828; border-radius:8px; font-size:13px; }}
  .advice h3 {{ margin:0 0 6px; font-size:13px; color:var(--warn); }}
  .advice ul {{ margin:4px 0; padding-left:18px; }}
  .advice li {{ margin:3px 0; }}
  .match-report {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
                   padding:14px 16px; margin-bottom:14px; }}
  .match-report h2 {{ margin:0; font-size:14px; color:var(--dim); }}
  .match-report-head {{ display:flex; align-items:center; justify-content:space-between;
                        gap:12px; margin-bottom:12px; flex-wrap:wrap; }}
  .match-nav {{ display:flex; gap:8px; }}
  .match-nav button {{ background:#0f1828; color:var(--text); border:1px solid var(--border);
                       border-radius:6px; padding:5px 12px; font-size:12px; cursor:pointer; }}
  .match-nav button:hover:not(:disabled) {{ border-color:var(--accent); color:var(--accent); }}
  .match-nav button:disabled {{ opacity:0.35; cursor:not-allowed; }}
  .scoreline {{ display:flex; align-items:center; gap:14px; margin-bottom:12px; flex-wrap:wrap; }}
  .scoreline .nums {{ font-size:28px; font-weight:700; letter-spacing:2px; }}
  .scoreline .badge {{ font-size:12px; padding:3px 10px; border-radius:12px; font-weight:600; }}
  .badge.win {{ background:rgba(52,195,126,0.2); color:var(--good); }}
  .badge.loss {{ background:rgba(239,83,80,0.2); color:var(--bad); }}
  .badge.draw {{ background:rgba(245,166,35,0.2); color:var(--warn); }}
  .badge.live {{ background:rgba(79,142,247,0.2); color:var(--accent); }}
  .stat-row {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin-bottom:12px; }}
  .stat-box {{ background:#0f1828; border-radius:8px; padding:10px 12px; }}
  .stat-box .label {{ font-size:11px; color:var(--dim); margin-bottom:4px; }}
  .stat-box .val {{ font-size:18px; font-weight:600; }}
  .poss-bar {{ height:8px; border-radius:4px; overflow:hidden; display:flex; margin-top:6px; }}
  .poss-bar .us {{ background:var(--accent); }}
  .poss-bar .them {{ background:var(--bad); }}
  .poss-bar .loose {{ background:#243049; }}
  .goal-list {{ list-style:none; margin:0; padding:0; }}
  .goal-list li {{ display:flex; gap:10px; align-items:baseline; padding:6px 0; border-bottom:1px solid var(--border); font-size:13px; }}
  .goal-list li:last-child {{ border-bottom:none; }}
  .goal-list .min {{ color:var(--dim); min-width:36px; font-variant-numeric:tabular-nums; }}
  .goal-list .us-goal {{ color:var(--good); }}
  .goal-list .opp-goal {{ color:var(--bad); }}
  .match-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  .match-table th, .match-table td {{ padding:6px 8px; text-align:left; border-bottom:1px solid var(--border); }}
  .match-table th {{ color:var(--dim); font-weight:500; }}
  .match-bar {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px;
                padding:10px 12px; background:var(--card); border:1px solid var(--border); border-radius:10px; }}
  .match-bar-label {{ font-size:13px; font-weight:600; color:var(--text); white-space:nowrap; }}
  .match-bar select#matchSelect {{ min-width:280px; max-width:100%; flex:1; font-size:13px; }}
  .match-bar-hint {{ font-size:12px; color:var(--dim); }}
  #err {{ color:var(--bad); padding:20px; text-align:center; }}
  .loading {{ color:var(--dim); font-style:italic; }}
</style>
</head>
<body>
<header>
  <h1 data-i18n="analytics.title"></h1>
  {nav_header("analytics")}
  <span id="meta" class="loading" data-i18n="common.loading"></span>
  <div class="controls">
    <select id="minutes">
      <option value="60" data-i18n="analytics.minutes.60"></option>
      <option value="180" selected data-i18n="analytics.minutes.180"></option>
      <option value="360" data-i18n="analytics.minutes.360"></option>
      <option value="720" data-i18n="analytics.minutes.720"></option>
    </select>
    <select id="advisorModel" data-i18n-title="analytics.advise"></select>
    <button id="refresh" data-i18n="analytics.refresh_data"></button>
    <button id="advise" data-i18n="analytics.advise"></button>
  </div>
</header>
<main>
  <div id="err" style="display:none"></div>
  <div class="match-bar">
    <span class="match-bar-label" data-i18n="analytics.select_match"></span>
    <select id="matchSelect"></select>
    <span class="match-bar-hint" data-i18n="analytics.select_match_hint"></span>
  </div>
  <div class="match-report" id="matchReport" style="display:none"></div>
  <div class="grid">
    <div class="panel">
      <h2><span data-i18n="analytics.heatmap"></span> <span id="hmLabel"></span></h2>
      <div class="pos-tabs" id="posTabs"></div>
      <div class="pitch-wrap"><canvas id="pitch"></canvas></div>
      <div class="legend" id="legend"></div>
    </div>
    <div class="panel">
      <h2 id="playerTitle" data-i18n="analytics.player_stats"></h2>
      <div class="stats" id="stats"></div>
      <div class="advice" id="adviceBox"></div>
    </div>
  </div>
</main>
<script>
{I18N_SCRIPT}
const POS = ["ALL","GK","DEF","MID","FWD1","FWD2"];
const COLORS = {{ GK:"#4f8ef7", DEF:"#34c37e", MID:"#f5a623", FWD1:"#ef5350", FWD2:"#ab47bc", ALL:"#888" }};
const DEFAULT_FIELD = {{
  x_min:-55, x_max:55, y_min:-30, y_max:30,
  length:110, width:60, label:"5v5",
  center_circle_r:9, box_depth:16.5, box_half_width:18,
  goal_half_width:7,
  goal_x_own:-55, goal_x_opp:55,
  scale_x:55/7, scale_y:30/3.5,
}};
let data = null, selPos = "ALL", adviceCache = null, pitchCtx = null;
const MODEL_STORAGE_KEY = "analytics_advisor_model";
const MATCH_STORAGE_KEY = "analytics_match";

function matchValue(m) {{
  return m.match_id || String(m.index);
}}

function matchLabel(m) {{
  const tag = m.match_id ? m.match_id.slice(0, 8) + "…" : `#${{m.index + 1}}`;
  const live = m.in_progress ? ` · ${{t("analytics.match_live")}}` : "";
  const poss = m.possession_our_pct != null ? ` · ${{m.possession_our_pct}}%` : "";
  const noLog = m.no_logs ? ` · ${{t("analytics.no_logs")}}` : "";
  const ticks = m.no_logs ? "" : ` · ${{m.ticks}}t`;
  return `${{tag}} · ${{m.score}}${{poss}}${{ticks}}${{live}}${{noLog}}`;
}}

function selectedMatchParam() {{
  const v = document.getElementById("matchSelect").value;
  localStorage.setItem(MATCH_STORAGE_KEY, v);
  return v === "all" ? "" : `&match=${{encodeURIComponent(v)}}`;
}}

function fillMatchSelect(matches, selectedIndex, selectedId) {{
  const sel = document.getElementById("matchSelect");
  const saved = localStorage.getItem(MATCH_STORAGE_KEY);
  let pick = "all";
  if (selectedId) pick = selectedId;
  else if (selectedIndex != null) pick = String(selectedIndex);
  else if (saved) pick = saved;
  const opts = [`<option value="all">${{t("analytics.match_all")}}</option>`];
  for (const m of (matches || [])) {{
    const val = matchValue(m);
    opts.push(`<option value="${{val}}"${{val === pick ? " selected" : ""}}>${{matchLabel(m)}}</option>`);
  }}
  sel.innerHTML = opts.join("");
  sel.title = t("analytics.select_match");
}}

function matchOptionValues() {{
  return Array.from(document.getElementById("matchSelect").options)
    .map(o => o.value).filter(v => v !== "all");
}}

function currentMatchIdx() {{
  const v = document.getElementById("matchSelect").value;
  return v === "all" ? -1 : matchOptionValues().indexOf(v);
}}

function navigateMatch(delta) {{
  const opts = matchOptionValues();
  const idx = currentMatchIdx();
  if (idx < 0) return;
  const target = idx + delta;
  if (target < 0 || target >= opts.length) return;
  document.getElementById("matchSelect").value = opts[target];
  selectedMatchParam();
  adviceCache = null;
  loadData(false);
}}

function bindMatchNav() {{
  const idx = currentMatchIdx();
  const opts = matchOptionValues();
  const prev = document.getElementById("matchPrev");
  const next = document.getElementById("matchNext");
  if (!prev || !next) return;
  prev.disabled = idx < 0 || idx >= opts.length - 1;
  next.disabled = idx <= 0;
  prev.onclick = () => navigateMatch(1);
  next.onclick = () => navigateMatch(-1);
}}

function renderMatchReport(j) {{
  const box = document.getElementById("matchReport");
  const rep = j.match_report;
  if (rep) {{
    const sc = rep.score || {{}};
    const poss = rep.possession || {{}};
    const terr = rep.territory || {{}};
    let badge = "";
    if (rep.in_progress) badge = `<span class="badge live">${{t("analytics.match_live")}}</span>`;
    else if (sc.won) badge = `<span class="badge win">${{t("analytics.result_win")}}</span>`;
    else if (sc.lost) badge = `<span class="badge loss">${{t("analytics.result_loss")}}</span>`;
    else if (sc.draw) badge = `<span class="badge draw">${{t("analytics.result_draw")}}</span>`;
    const goals = (rep.goals || []).map(g => {{
      const cls = g.team === "us" ? "us-goal" : "opp-goal";
      const who = g.team === "us" ? t("analytics.goal_us") : t("analytics.goal_opp");
      const scorer = g.scorer ? ` · ${{t("analytics.goal_scorer", {{pos: g.scorer}})}}` : "";
      return `<li><span class="min">${{g.minute}}</span><span class="${{cls}}">${{who}}${{scorer}}</span><span style="color:var(--dim)">${{g.score_after}}</span></li>`;
    }}).join("") || `<li style="color:var(--dim)">${{t("analytics.no_goals")}}</li>`;
    const usP = poss.our_pct ?? 0, oppP = poss.opp_pct ?? 0, looseP = poss.loose_pct ?? 0;
    const grindHint = rep.from_grind
      ? `<p style="color:var(--warn);font-size:12px;margin:0 0 10px">${{t("analytics.grind_only_hint")}}</p>`
      : "";
    box.style.display = "block";
    box.innerHTML = `
      <div class="match-report-head">
        <h2 data-i18n="analytics.match_data"></h2>
        <div class="match-nav">
          <button type="button" id="matchPrev" data-i18n="analytics.match_prev"></button>
          <button type="button" id="matchNext" data-i18n="analytics.match_next"></button>
        </div>
      </div>
      ${{grindHint}}
      <div class="scoreline">
        <span class="nums">${{sc.home ?? 0}} : ${{sc.away ?? 0}}</span>
        ${{badge}}
        <span style="color:var(--dim);font-size:13px">${{t("analytics.final_score")}}</span>
      </div>
      <div class="stat-row">
        <div class="stat-box">
          <div class="label">${{t("analytics.possession")}}</div>
          <div class="val">${{usP}}% : ${{oppP}}%</div>
          <div class="poss-bar"><div class="us" style="width:${{usP}}%"></div><div class="them" style="width:${{oppP}}%"></div><div class="loose" style="width:${{looseP}}%"></div></div>
        </div>
        <div class="stat-box">
          <div class="label">${{t("analytics.territory")}}</div>
          <div class="val">${{terr.opp_half_pct ?? "—"}}%</div>
        </div>
        <div class="stat-box">
          <div class="label">${{t("analytics.our_shots")}}</div>
          <div class="val">${{rep.shots?.our_attempts ?? "—"}}</div>
        </div>
      </div>
      <h3 style="font-size:12px;color:var(--dim);margin:0 0 6px">${{t("analytics.goals")}}</h3>
      <ul class="goal-list">${{goals}}</ul>`;
    applyI18n();
    bindMatchNav();
    return;
  }}
  const reports = j.matches || [];
  if (reports.length && !rep) {{
    box.style.display = "block";
    box.innerHTML = `
      <h2 data-i18n="analytics.match_list"></h2>
      <p style="color:var(--dim);font-size:12px;margin:0 0 10px">${{t("analytics.select_match_hint")}}</p>
      <table class="match-table">
        <tr><th>${{t("analytics.final_score")}}</th><th>${{t("analytics.possession")}}</th><th>${{t("analytics.goals")}}</th><th>${{t("analytics.our_shots")}}</th><th></th></tr>
        ${{reports.slice().reverse().map(m => {{
          const res = m.in_progress ? t("analytics.match_live")
            : m.won ? t("analytics.result_win") : (m.home_score === m.away_score ? t("analytics.result_draw") : t("analytics.result_loss"));
          return `<tr><td>${{m.score ?? "—"}} <span style="color:var(--dim)">(${{res}})</span></td>
            <td>${{m.possession_our_pct ?? "—"}}% / ${{m.possession_opp_pct ?? "—"}}%</td>
            <td>${{m.goals_count ?? 0}}</td>
            <td>${{m.shots ?? "—"}}</td>
            <td><button type="button" data-match="${{matchValue(m)}}" style="font-size:11px;padding:2px 8px">${{t("analytics.pick_match")}}</button></td></tr>`;
        }}).join("")}}
      </table>`;
    applyI18n();
    box.querySelectorAll("button[data-match]").forEach(btn => {{
      btn.onclick = () => {{
        document.getElementById("matchSelect").value = btn.dataset.match;
        loadData(false);
      }};
    }});
    return;
  }}
  box.style.display = "none";
  box.innerHTML = "";
}}

function modelLabel(m) {{
  if (lang === "en" && m.label_en) return m.label_en;
  return m.label || m.id;
}}

function fillAdvisorModels(models, selected) {{
  const sel = document.getElementById("advisorModel");
  const list = models?.length ? models : [
    {{id:"us.amazon.nova-2-lite-v1:0", label:"Nova 2 Lite（推荐）", label_en:"Nova 2 Lite (recommended)"}},
    {{id:"us.anthropic.claude-sonnet-4-6", label:"Claude Sonnet 4.6", label_en:"Claude Sonnet 4.6"}},
    {{id:"us.anthropic.claude-haiku-4-5-20251001-v1:0", label:"Claude Haiku 4.5", label_en:"Claude Haiku 4.5"}},
    {{id:"us.amazon.nova-micro-v1:0", label:"Nova Micro（快）", label_en:"Nova Micro (fast)"}},
  ];
  const saved = localStorage.getItem(MODEL_STORAGE_KEY);
  const pick = selected || saved || list[0].id;
  sel.innerHTML = list.map(m =>
    `<option value="${{m.id}}"${{m.id === pick ? " selected" : ""}}>${{modelLabel(m)}}</option>`).join("");
}}

function selectedAdvisorModel() {{
  const id = document.getElementById("advisorModel").value;
  localStorage.setItem(MODEL_STORAGE_KEY, id);
  return id;
}}

function fieldAspect(field) {{
  const w = field.x_max - field.x_min, h = field.y_max - field.y_min;
  return h > 0 ? w / h : 11 / 6;
}}

function updateLegend(field) {{
  const er = data?.engine_range;
  const erTxt = er?.mx ? ` · mx∈[${{er.mx[0]}},${{er.mx[1]}}]` : "";
  const sx = field.scale_x ?? (55/7);
  const sy = field.scale_y ?? (30/3.5);
  document.getElementById("legend").textContent = t("analytics.legend", {{
    len: field.length, wid: field.width, er: erTxt, sx: sx.toFixed(2), sy: sy.toFixed(2),
  }});
}}

function pitchSize(field) {{
  const wrap = document.querySelector(".pitch-wrap");
  const c = document.getElementById("pitch");
  const w = Math.max(wrap.clientWidth, 440);
  const ar = fieldAspect(field);
  const h = w / ar;
  wrap.style.aspectRatio = `${{Math.round(ar * 100)}}/${{100}}`;
  const dpr = window.devicePixelRatio || 1;
  c.width = Math.round(w * dpr);
  c.height = Math.round(h * dpr);
  c.style.width = w + "px";
  c.style.height = h + "px";
  pitchCtx = c.getContext("2d");
  pitchCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {{ W: w, H: h }};
}}

function pitchLayout(W, H, field) {{
  const fx0 = field.x_min, fx1 = field.x_max, fy0 = field.y_min, fy1 = field.y_max;
  const fieldW = fx1 - fx0, fieldH = fy1 - fy0;
  const tx = x => (x - fx0) / fieldW * W;
  const ty = y => (fy1 - y) / fieldH * H;
  return {{ tx, ty, W, H, field }};
}}

function drawPitchMarkings(ctx, layout) {{
  const {{ tx, ty, W, field }} = layout;
  const {{ x_min, x_max, y_min, y_max }} = field;
  const bx = field.box_half_width ?? 18;
  const bd = field.box_depth ?? 16.5;
  const cr = field.center_circle_r ?? 9;
  const gw = field.goal_half_width ?? 7;
  const gOwn = field.goal_x_own ?? -55;
  const gOpp = field.goal_x_opp ?? 55;
  const m = tx(x_min + 1) - tx(x_min);

  ctx.fillStyle = "#1a4d2e";
  ctx.fillRect(0, ty(y_max), W, ty(y_min) - ty(y_max));
  ctx.strokeStyle = "rgba(255,255,255,0.85)";
  ctx.lineWidth = 2;
  ctx.strokeRect(tx(x_min), ty(y_max), tx(x_max) - tx(x_min), ty(y_min) - ty(y_max));
  ctx.beginPath();
  ctx.moveTo(tx(0), ty(y_max)); ctx.lineTo(tx(0), ty(y_min)); ctx.stroke();
  ctx.beginPath();
  ctx.arc(tx(0), ty(0), cr * m, 0, Math.PI * 2);
  ctx.stroke();
  for (const gx of [gOwn, gOpp]) {{
    const inX = gx < 0 ? gx + bd : gx - bd;
    const x0 = tx(Math.max(x_min, Math.min(gx, inX)));
    const x1 = tx(Math.min(x_max, Math.max(gx, inX)));
    if (x1 > x0) ctx.strokeRect(x0, ty(bx), x1 - x0, ty(-bx) - ty(bx));
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(tx(gx), ty(gw)); ctx.lineTo(tx(gx), ty(-gw));
    ctx.stroke(); ctx.lineWidth = 2;
  }}
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "11px system-ui,sans-serif";
  ctx.fillText(t("analytics.own_goal"), tx(x_min) + 6, ty(y_max) - 8);
  ctx.fillText(t("analytics.opp_goal"), tx(x_max) - 72, ty(y_max) - 8);
}}

function colorAlpha(hex, a) {{
  if (!hex || hex[0] !== "#") return `rgba(136,136,136,${{a}})`;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${{r}},${{g}},${{b}},${{a}})`;
}}

function roleColor(pos) {{
  return COLORS[pos] || COLORS.ALL;
}}

function drawPitch(hm) {{
  if (!hm) return;
  const field = {{ ...DEFAULT_FIELD, ...(data?.field || {{}}), ...(hm.bounds || {{}}) }};
  const {{ W, H }} = pitchSize(field);
  const ctx = pitchCtx;
  const layout = pitchLayout(W, H, field);
  const {{ tx, ty }} = layout;
  const viewAll = !hm.pos || hm.pos === "ALL";
  const heatColor = viewAll ? "#ffc832" : roleColor(hm.pos);
  updateLegend(field);
  drawPitchMarkings(ctx, layout);
  const [gx, gy] = hm.grid;
  const fx0 = field.x_min, fx1 = field.x_max, fy0 = field.y_min, fy1 = field.y_max;
  const fieldW = fx1 - fx0, fieldH = fy1 - fy0;
  for (const cell of (hm.cells || [])) {{
    const xA = fx0 + cell.ix * fieldW / gx;
    const xB = fx0 + (cell.ix + 1) * fieldW / gx;
    const yLow = fy0 + cell.iy * fieldH / gy;
    const yHigh = fy0 + (cell.iy + 1) * fieldH / gy;
    const a = Math.min(0.85, 0.1 + cell.intensity * 0.72);
    ctx.fillStyle = colorAlpha(heatColor, a);
    ctx.fillRect(tx(xA), ty(yHigh), tx(xB) - tx(xA), ty(yLow) - ty(yHigh));
  }}
  for (const p of (hm.trail || [])) {{
    const col = viewAll ? roleColor(p.pos) : roleColor(hm.pos);
    ctx.fillStyle = colorAlpha(col, 0.62);
    ctx.strokeStyle = colorAlpha(col, 0.95);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(tx(p.x), ty(p.y), viewAll ? 3.2 : 3.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }}
  for (const s of (hm.shots || [])) {{
    const col = viewAll ? roleColor(s.pos) : roleColor(hm.pos);
    ctx.fillStyle = colorAlpha(col, 0.95);
    ctx.strokeStyle = "rgba(0,0,0,0.55)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(tx(s.x), ty(s.y), 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 8px system-ui,sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("S", tx(s.x), ty(s.y));
  }}
}}

function renderStats(p) {{
  if (!p) return `<p class='loading'>${{t("analytics.no_data")}}</p>`;
  const cmd = Object.entries(p.commands||{{}}).map(([k,v]) =>
    `<div>${{k}}: ${{v}}</div><div class="bar"><i style="width:${{100*v/p.ticks}}%"></i></div>`).join("");
  const ov = Object.entries(p.overrides||{{}}).slice(0,5).map(([k,v])=>`${{k}}:${{v}}`).join(" · ");
  return `<dl>
    <dt>${{t("common.ticks")}}</dt><dd>${{p.ticks}}</dd>
    <dt>${{t("analytics.avg_pos")}}</dt><dd>(${{p.avg_position?.x??"—"}}, ${{p.avg_position?.y??"—"}})</dd>
    <dt>${{t("analytics.dist_own")}}</dt><dd>${{p.avg_dist_own_goal??"—"}}</dd>
    <dt>${{t("analytics.dist_opp")}}</dt><dd>${{p.avg_dist_opp_goal??"—"}}</dd>
    <dt>${{t("analytics.zone_split")}}</dt><dd>${{t("analytics.zone_own")}} ${{p.zone_pct?.own_half??"—"}}% / ${{t("analytics.zone_opp")}} ${{p.zone_pct?.opp_half??"—"}}%</dd>
    <dt>${{t("analytics.shot_discipline")}}</dt><dd>${{p.shots_taken??0}}/${{p.shot_chances??0}} (${{p.shot_discipline_pct??"—"}}%)</dd>
    <dt>${{t("analytics.override_fixes")}}</dt><dd>${{p.override_fixes??0}} ${{t("analytics.times")}}</dd>
    <dt>${{t("analytics.llm_ratio")}}</dt><dd>${{p.llm_ratio!=null?Math.round(p.llm_ratio*100)+"%":"—"}}</dd>
    <dt>${{t("analytics.latency_p95")}}</dt><dd>${{p.latency?.p95??"—"}} ms</dd>
  </dl>
  <h3 style="font-size:12px;color:var(--dim);margin:12px 0 4px">${{t("analytics.cmd_dist")}}</h3>${{cmd}}
  <p style="font-size:11px;color:var(--dim);margin-top:8px">override: ${{ov||"—"}}</p>`;
}}

function advicePlaceholder() {{
  return `<div class='loading'>${{t("analytics.advice_placeholder")}}</div>`;
}}

function renderAdvice(adv, pos) {{
  if (!adv) return advicePlaceholder();
  if (adv.error) return `<p style="color:var(--bad)"><strong>${{t("analytics.advice_failed")}}</strong><br>${{adv.error}}</p>`;
  const pl = adv.players?.[pos];
  if (!pl) return `<p class='loading'>${{t("analytics.advice_no_pos")}}</p>`;
  const sec = (title, arr) => arr?.length
    ? `<h3>${{title}}</h3><ul>${{arr.map(x=>`<li>${{x}}</li>`).join("")}}</ul>` : "";
  const tuning = Object.entries(pl.tuning_changes||{{}}).map(([k,v])=>`${{k}} → ${{v}}`);
  return `<p><strong>${{pl.summary||""}}</strong></p>
    ${{adviceCache?.model ? `<p style="font-size:11px;color:var(--dim)">${{t("analytics.model")}}: ${{adviceCache.model}}</p>` : ""}}
    ${{sec(t("analytics.prompt_changes"), pl.prompt_changes)}}
    ${{sec(t("analytics.tuning_changes"), tuning)}}
    ${{sec(t("analytics.code_changes"), pl.code_changes)}}`;
}}

function selectPos(pos) {{
  selPos = pos;
  document.querySelectorAll("#posTabs button").forEach(b =>
    b.classList.toggle("active", b.dataset.pos === pos));
  const hm = data?.heatmaps?.[pos];
  document.getElementById("hmLabel").textContent = hm
    ? `(${{hm.samples}} ${{t("analytics.samples")}})` : "";
  if (hm) drawPitch(hm);
  const prof = data?.profiles?.find(p => p.pos === pos);
  document.getElementById("playerTitle").textContent =
    pos === "ALL" ? t("analytics.team_overview") : t("analytics.player_analysis", {{pos}});
  document.getElementById("stats").innerHTML = pos === "ALL"
    ? (data?.match_report
        ? `<p>${{t("analytics.matches_summary", {{ticks: data?.ticks||0, matches: 1}})}}</p>`
        : `<p>${{t("analytics.matches_summary", {{ticks: data?.ticks||0, matches: data?.matches_detected||0}})}}</p>`)
    : renderStats(prof);
  document.getElementById("adviceBox").innerHTML = pos === "ALL"
    ? (adviceCache?.team
        ? `<p><strong>${{adviceCache.team.summary||""}}</strong></p>
           ${{adviceCache.model ? `<p style="font-size:11px;color:var(--dim)">${{t("analytics.model")}}: ${{adviceCache.model}}</p>` : ""}}
           <ul>${{(adviceCache.team.priority||[]).map(x=>`<li>${{x}}</li>`).join("")}}</ul>`
        : (adviceCache ? `<p class='loading'>${{t("analytics.advice_no_team")}}</p>` : advicePlaceholder()))
    : renderAdvice(adviceCache, pos);
}}

async function loadData(syncCloud=false) {{
  const minutes = document.getElementById("minutes").value;
  document.getElementById("meta").textContent =
    syncCloud ? t("analytics.querying") : t("analytics.loading_local");
  const sync = syncCloud ? "&sync=1" : "";
  const res = await fetch(`/api/analytics?minutes=${{minutes}}${{selectedMatchParam()}}${{sync}}`);
  const j = await res.json();
  if (j.error) {{
    document.getElementById("err").style.display = "block";
    document.getElementById("err").textContent = j.error_key ? t(j.error_key) : j.error;
    return;
  }}
  document.getElementById("err").style.display = "none";
  data = j;
  adviceCache = null;
  fillAdvisorModels(j.advisor_models, j.advisor_model_default);
  fillMatchSelect(j.matches, j.selected_match, j.selected_match_id);
  const matchSel = document.getElementById("matchSelect");
  if ((j.matches||[]).length >= 1 && matchSel.value === "all") {{
    const withLogs = (j.matches||[]).filter(m => !m.no_logs);
    if (withLogs.length === 1) {{
      matchSel.value = matchValue(withLogs[0]);
      selectedMatchParam();
      loadData(false);
      return;
    }}
  }}
  document.getElementById("adviceBox").innerHTML = advicePlaceholder();
  const selLabel = document.getElementById("matchSelect").selectedOptions[0]?.textContent || t("analytics.match_all");
  const cacheHint = j.local_store?.source === "local_cache" ? ` · ${{t("analytics.local_cache_hint")}}` : "";
  document.getElementById("meta").textContent =
    `${{t("analytics.viewing_match", {{label: selLabel}})}} · ${{j.ticks}} ticks · ${{j.generated_at}}`
    + cacheHint
    + (j.local_store?.saved_new ? ` · +${{j.local_store.saved_new}} saved` : "")
    + (j.local_store?.rows ? ` · local ${{j.local_store.rows}}` : "");
  renderMatchReport(j);
  document.getElementById("posTabs").innerHTML = POS.map(p =>
    `<button data-pos="${{p}}" style="border-color:${{COLORS[p]}}">${{p}}</button>`).join("");
  document.querySelectorAll("#posTabs button").forEach(b =>
    b.onclick = () => selectPos(b.dataset.pos));
  selectPos(selPos);
}}

async function loadAdvice() {{
  const box = document.getElementById("adviceBox");
  const btn = document.getElementById("advise");
  box.innerHTML = `<div class='loading'>${{t("analytics.advice_running")}}</div>`;
  btn.disabled = true;
  try {{
    const minutes = document.getElementById("minutes").value;
    const model = selectedAdvisorModel();
    const res = await fetch(`/api/advise?minutes=${{minutes}}${{selectedMatchParam()}}&model=${{encodeURIComponent(model)}}`);
    const j = await res.json();
    if (!res.ok && j.error) throw new Error(j.error);
    adviceCache = j;
    if (j.error) {{
      box.innerHTML = `<p style="color:var(--bad)"><strong>${{t("analytics.advice_failed")}}</strong><br>${{j.error}}</p>`;
      return;
    }}
    selectPos(selPos);
  }} catch (e) {{
    box.innerHTML = `<p style="color:var(--bad)"><strong>${{t("analytics.advice_failed")}}</strong><br>${{e.message||e}}</p>`;
  }} finally {{
    btn.disabled = false;
  }}
}}

document.getElementById("refresh").onclick = () => loadData(true);
document.getElementById("advise").onclick = loadAdvice;
document.getElementById("minutes").onchange = () => loadData(false);
document.getElementById("matchSelect").onchange = () => {{
  adviceCache = null;
  loadData(false);
}};
document.getElementById("advisorModel").onchange = () => {{
  selectedAdvisorModel();
  adviceCache = null;
  document.getElementById("adviceBox").innerHTML = advicePlaceholder();
}};
window.addEventListener("resize", () => {{ if (data) selectPos(selPos); }});
function onLangChanged() {{
  if (data) {{
    fillAdvisorModels(data.advisor_models, selectedAdvisorModel());
    fillMatchSelect(data.matches, data.selected_match, data.selected_match_id);
    renderMatchReport(data);
    selectPos(selPos);
  }}
}}
applyI18n();
document.getElementById("adviceBox").innerHTML = advicePlaceholder();
loadData(false);
</script>
</body>
</html>"""
