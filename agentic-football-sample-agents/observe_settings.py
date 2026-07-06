"""Settings page — AWS CLI credentials configuration."""

from observe_i18n import I18N_SCRIPT, SHARED_STYLES, nav_header

SETTINGS_PAGE = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Settings — Football Agents</title>
<style>
  :root {{ --bg:#0f1115; --card:#181b22; --line:#2a2f3a; --text:#e6e9ef;
          --dim:#9aa4b2; --accent:#4f8ef7; --good:#34c37e; --warn:#f5a623; --bad:#ef5350; --border:#2a2f3a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font:14px/1.5 "Segoe UI",system-ui,sans-serif; }}
  header {{ display:flex; align-items:center; gap:16px; padding:14px 22px;
           border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); z-index:5; }}
  header h1 {{ font-size:17px; margin:0; font-weight:600; }}
  {SHARED_STYLES}
  main {{ padding:18px 22px; max-width:720px; margin:0 auto; }}
  .panel {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
            padding:16px 18px; margin-bottom:16px; }}
  .panel h2 {{ margin:0 0 6px; font-size:15px; }}
  .panel p.desc {{ margin:0 0 14px; color:var(--dim); font-size:13px; }}
  label {{ display:block; font-size:12px; color:var(--dim); margin:10px 0 4px; }}
  input, select, textarea {{ width:100%; background:#0f1115; color:var(--text);
    border:1px solid var(--line); border-radius:6px; padding:8px 10px; font-size:13px; }}
  textarea {{ min-height:72px; font-family:ui-monospace,monospace; resize:vertical; }}
  .row {{ display:flex; gap:10px; margin-top:14px; flex-wrap:wrap; }}
  button {{ background:var(--card); color:var(--text); border:1px solid var(--line);
             border-radius:6px; padding:8px 14px; font-size:13px; cursor:pointer; }}
  button.primary {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
  button:disabled {{ opacity:0.5; cursor:not-allowed; }}
  .status {{ margin-top:12px; padding:10px 12px; border-radius:8px; font-size:13px; }}
  .status.ok {{ background:rgba(52,195,126,0.12); color:var(--good); border:1px solid rgba(52,195,126,0.35); }}
  .status.bad {{ background:rgba(239,83,80,0.12); color:var(--bad); border:1px solid rgba(239,83,80,0.35); }}
  .status.info {{ background:rgba(79,142,247,0.1); color:var(--accent); border:1px solid rgba(79,142,247,0.3); }}
  dl.status-grid {{ display:grid; grid-template-columns:120px 1fr; gap:6px 12px; margin:0; font-size:13px; }}
  dl.status-grid dt {{ color:var(--dim); }}
  dl.status-grid dd {{ margin:0; word-break:break-all; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; }}
  .badge.ok {{ background:rgba(52,195,126,0.2); color:var(--good); }}
  .badge.bad {{ background:rgba(239,83,80,0.2); color:var(--bad); }}
</style>
</head>
<body>
<header>
  <h1 data-i18n="settings.title"></h1>
  {nav_header("settings")}
</header>
<main>
  <div class="panel">
    <h2 data-i18n="settings.aws_heading"></h2>
    <p class="desc" data-i18n="settings.aws_desc"></p>
    <label data-i18n="settings.profile"></label>
    <input id="profile" value="default" autocomplete="off">
    <label data-i18n="settings.access_key"></label>
    <input id="accessKey" autocomplete="off" placeholder="AKIA...">
    <label data-i18n="settings.secret_key"></label>
    <input id="secretKey" type="password" autocomplete="new-password">
    <label data-i18n="settings.session_token"></label>
    <textarea id="sessionToken" autocomplete="off" placeholder="Workshop / SSO session token"></textarea>
    <label data-i18n="settings.region"></label>
    <select id="region">
      <option value="us-east-1">us-east-1</option>
      <option value="us-west-2">us-west-2</option>
      <option value="eu-west-1">eu-west-1</option>
      <option value="ap-southeast-1">ap-southeast-1</option>
    </select>
    <div class="row">
      <button type="button" class="primary" id="saveBtn" data-i18n="settings.save"></button>
      <button type="button" id="testBtn" data-i18n="settings.test"></button>
    </div>
    <div id="formMsg"></div>
  </div>

  <div class="panel">
    <h2 data-i18n="settings.data_heading"></h2>
    <p class="desc" data-i18n="settings.data_desc"></p>
    <label data-i18n="settings.data_prefix"></label>
    <input id="cwPrefix" value="agg_" autocomplete="off">
    <label data-i18n="settings.data_minutes"></label>
    <select id="cwMinutes">
      <option value="60">60 min</option>
      <option value="180" selected>3 hours</option>
      <option value="360">6 hours</option>
      <option value="720">12 hours</option>
      <option value="1440">24 hours</option>
    </select>
    <div class="row">
      <button type="button" class="primary" id="downloadBtn" data-i18n="settings.data_download"></button>
    </div>
    <div id="dataMsg"></div>
    <h3 style="font-size:13px;margin:16px 0 8px;color:var(--dim)" data-i18n="settings.data_local"></h3>
    <div id="localStoreBox"><p class="desc" data-i18n="common.loading"></p></div>
  </div>

  <div class="panel">
    <h2 data-i18n="settings.current"></h2>
    <div id="statusBox"><p class="desc" data-i18n="common.loading"></p></div>
  </div>
</main>
<script>
{I18N_SCRIPT}

function showFormMsg(text, kind) {{
  const el = document.getElementById("formMsg");
  el.className = "status " + (kind || "info");
  el.textContent = text;
}}

function showDataMsg(text, kind) {{
  const el = document.getElementById("dataMsg");
  el.className = "status " + (kind || "info");
  el.textContent = text;
}}

function renderLocalStore(st) {{
  const box = document.getElementById("localStoreBox");
  if (!st || !st.rows) {{
    box.innerHTML = `<p class="desc">${{t("settings.data_local_empty")}}</p>`;
    return;
  }}
  const range = (st.oldest && st.newest)
    ? t("settings.data_local_range", {{ oldest: st.oldest, newest: st.newest }})
    : "—";
  box.innerHTML = `
    <dl class="status-grid">
      <dt>${{t("settings.path")}}</dt><dd>${{st.dir || "—"}}</dd>
      <dt>${{t("settings.data_prefix")}}</dt><dd>${{st.prefix || "—"}}</dd>
      <dt>${{t("settings.data_local")}}</dt><dd>${{t("settings.data_local_rows", {{ rows: st.rows }})}} · ${{t("settings.data_local_files", {{ files: st.files || 0 }})}}</dd>
      <dt>Range</dt><dd>${{range}}</dd>
    </dl>`;
}}

async function loadLocalStore() {{
  const pfx = document.getElementById("cwPrefix").value.trim() || "agg_";
  const res = await fetch(`/api/cloud/store?prefix=${{encodeURIComponent(pfx)}}`);
  renderLocalStore(await res.json());
}}

function renderStatus(st) {{
  const box = document.getElementById("statusBox");
  if (!st) {{
    box.innerHTML = `<p class="desc">${{t("common.error")}}</p>`;
    return;
  }}
  const badge = st.valid
    ? `<span class="badge ok">${{t("settings.valid")}}</span>`
    : `<span class="badge bad">${{t("settings.invalid")}}</span>`;
  box.innerHTML = `
    <p style="margin:0 0 10px">${{badge}}</p>
    <dl class="status-grid">
      <dt>${{t("settings.path")}}</dt><dd>${{st.credentials_path || "—"}}</dd>
      <dt>${{t("settings.profile")}}</dt><dd>${{st.profile || "default"}}</dd>
      <dt>${{t("settings.access_key")}}</dt><dd>${{st.access_key_masked || "—"}}</dd>
      <dt>${{t("settings.secret_key")}}</dt><dd>${{st.secret_masked ? "••••" + st.secret_masked : "—"}}</dd>
      <dt>${{t("settings.session_token")}}</dt><dd>${{st.has_session_token ? st.session_token_masked : "—"}}</dd>
      <dt>${{t("settings.region")}}</dt><dd>${{st.region || "—"}}</dd>
      <dt>${{t("settings.account")}}</dt><dd>${{st.account || "—"}}</dd>
      <dt>${{t("settings.arn")}}</dt><dd>${{st.arn || (st.error || "—")}}</dd>
    </dl>`;
  if (st.access_key_id && !document.getElementById("accessKey").value) {{
    document.getElementById("accessKey").value = st.access_key_id;
  }}
  if (st.region) document.getElementById("region").value = st.region;
}}

async function loadStatus() {{
  const res = await fetch("/api/settings/aws");
  const st = await res.json();
  renderStatus(st);
  return st;
}}

function formPayload() {{
  return {{
    profile: document.getElementById("profile").value.trim() || "default",
    access_key_id: document.getElementById("accessKey").value.trim(),
    secret_access_key: document.getElementById("secretKey").value.trim(),
    session_token: document.getElementById("sessionToken").value.trim() || null,
    region: document.getElementById("region").value,
  }};
}}

document.getElementById("saveBtn").onclick = async () => {{
  const p = formPayload();
  if (!p.access_key_id || !p.secret_access_key) {{
    showFormMsg(t("settings.required"), "bad");
    return;
  }}
  const btn = document.getElementById("saveBtn");
  btn.disabled = true;
  try {{
    const res = await fetch("/api/settings/aws", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(p),
    }});
    const j = await res.json();
    if (j.error) throw new Error(j.error);
    showFormMsg(t("settings.saved"), "ok");
    document.getElementById("secretKey").value = "";
    document.getElementById("sessionToken").value = "";
    await loadStatus();
  }} catch (e) {{
    showFormMsg(e.message || String(e), "bad");
  }} finally {{
    btn.disabled = false;
  }}
}};

document.getElementById("testBtn").onclick = async () => {{
  const p = formPayload();
  if (!p.access_key_id || !p.secret_access_key) {{
    showFormMsg(t("settings.required"), "bad");
    return;
  }}
  const btn = document.getElementById("testBtn");
  btn.disabled = true;
  showFormMsg(t("common.loading"), "info");
  try {{
    const res = await fetch("/api/settings/aws/test", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(p),
    }});
    const j = await res.json();
    if (j.valid) {{
      showFormMsg(`${{t("settings.test_ok")}} · Account ${{j.account}} · ${{j.arn}}`, "ok");
    }} else {{
      showFormMsg(`${{t("settings.test_fail")}}: ${{j.error}}`, "bad");
    }}
  }} catch (e) {{
    showFormMsg(e.message || String(e), "bad");
  }} finally {{
    btn.disabled = false;
  }}
}};

document.getElementById("downloadBtn").onclick = async () => {{
  const btn = document.getElementById("downloadBtn");
  const pfx = document.getElementById("cwPrefix").value.trim() || "agg_";
  const minutes = document.getElementById("cwMinutes").value;
  btn.disabled = true;
  showDataMsg(t("settings.data_downloading"), "info");
  try {{
    const url = `/api/settings/cloudwatch/download?prefix=${{encodeURIComponent(pfx)}}&minutes=${{minutes}}`;
    const res = await fetch(url);
    if (!res.ok) {{
      let msg = t("settings.data_fail");
      try {{
        const j = await res.json();
        msg = j.error_key ? t(j.error_key) : (j.error || msg);
      }} catch (_) {{}}
      throw new Error(msg);
    }}
    const blob = await res.blob();
    const rows = res.headers.get("X-Rows-Total") || "?";
    const cloud = res.headers.get("X-Rows-Cloud") || "?";
    const saved = res.headers.get("X-Rows-Saved") || "0";
    let filename = `${{pfx}}decisions.jsonl`;
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename=\"?([^\";]+)/);
    if (m) filename = m[1];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    showDataMsg(t("settings.data_ok", {{ rows, cloud, saved }}), "ok");
    await loadLocalStore();
  }} catch (e) {{
    showDataMsg(e.message || String(e), "bad");
  }} finally {{
    btn.disabled = false;
  }}
}};

document.getElementById("cwPrefix").addEventListener("change", loadLocalStore);

applyI18n();
loadStatus();
loadLocalStore();
</script>
</body>
</html>"""
