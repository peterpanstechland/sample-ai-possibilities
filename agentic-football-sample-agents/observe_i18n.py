"""Shared i18n strings and JS helper for observe dashboard pages."""

import json

STRINGS = {
    "zh": {
        "nav.observability": "观测台",
        "nav.analytics": "比赛分析",
        "nav.settings": "设置",
        "lang.toggle": "EN",
        "common.refresh": "刷新",
        "common.loading": "加载中…",
        "common.updated": "更新于",
        "common.error": "查询出错",
        "common.minutes": "分钟",
        "common.shots": "射门",
        "common.ticks": "ticks",
        "dash.title": "Football Agents 观测台",
        "dash.analytics_link": "比赛分析 →",
        "dash.source.cloud": "实战 (CloudWatch)",
        "dash.source.local": "训练场 (本地)",
        "dash.source.both": "对比：实战 vs 训练",
        "dash.minutes.15": "最近 15 分钟",
        "dash.minutes.30": "最近 30 分钟",
        "dash.minutes.60": "最近 60 分钟",
        "dash.minutes.180": "最近 3 小时",
        "dash.empty": "暂无数据 — 实战：先打一场比赛或调大时间窗口；训练场：先运行 training_ground.py。",
        "dash.lat_chart": "LLM 延迟随时间（ms，按位置着色，虚线 = 900ms 超时风险线）",
        "dash.cmd_chart": "指令分布（全队）",
        "dash.cmd_compare": "指令分布对比（占各自总 tick 的 %）",
        "dash.llm_decisions": "LLM 决策",
        "dash.shot_discipline": "把握射门",
        "dash.override_fixes": "代码纠偏",
        "dash.healthy": "健康 — 无建议",
        "dash.live_vs_train": "实战 vs 训练",
        "dash.live": "实战",
        "dash.train": "训练",
        "dash.shoot_pct": "射门 %",
        "dash.discipline_pct": "把握射门 %",
        "dash.move_pct": "MOVE_TO %",
        "dash.llm_pct": "LLM %",
        "dash.time_axis": "比赛/训练时间 s",
        "dash.compare_hint": "实战射门率比训练低 {n} 个百分点 — 检查实战状态注入（hasBall/TACTICS）或对手压迫下的决策",
        "analytics.title": "⚽ 比赛分析",
        "analytics.back": "← 观测台",
        "analytics.minutes.60": "60 分钟",
        "analytics.minutes.180": "3 小时",
        "analytics.minutes.360": "6 小时",
        "analytics.minutes.720": "12 小时",
        "analytics.refresh_data": "刷新数据",
        "analytics.advise": "AI 修改建议",
        "analytics.heatmap": "场上活动热力图",
        "analytics.samples": "采样",
        "analytics.player_stats": "球员数据",
        "analytics.team_overview": "全队概览",
        "analytics.player_analysis": "{pos} 数据分析",
        "analytics.legend": "逻辑场 {len}×{wid}（x±55 y±30）{er} · 映射: x×{sx} y×{sy} · 左=己方球门",
        "analytics.own_goal": "己方 x=-55",
        "analytics.opp_goal": "对方 x=+55",
        "analytics.avg_pos": "平均位置",
        "analytics.dist_own": "距己方球门",
        "analytics.dist_opp": "距对方球门",
        "analytics.zone_split": "半场分布",
        "analytics.zone_own": "己方",
        "analytics.zone_opp": "进攻",
        "analytics.shot_discipline": "把握射门",
        "analytics.override_fixes": "代码纠偏",
        "analytics.llm_ratio": "LLM 占比",
        "analytics.latency_p95": "p95 延迟",
        "analytics.cmd_dist": "指令分布",
        "analytics.times": "次",
        "analytics.advice_placeholder": "点击右上角「AI 修改建议」生成分析（约 20–40s，需 Bedrock 权限）",
        "analytics.advice_running": "AI 分析中（约 20–40s）…",
        "analytics.advice_failed": "分析失败",
        "analytics.advice_no_pos": "该位置暂无 AI 建议（Claude 返回结构不完整）",
        "analytics.advice_no_team": "暂无全队总结",
        "analytics.model": "模型",
        "analytics.prompt_changes": "Prompt 修改",
        "analytics.tuning_changes": "tuning.json",
        "analytics.code_changes": "代码 (lib/)",
        "analytics.match_ticks": "{score} · {ticks}t · {shots} 射",
        "analytics.querying": "查询 CloudWatch…",
        "analytics.loading_local": "加载本地缓存…",
        "analytics.local_cache_hint": "本地缓存 · 点 Refresh 同步 CloudWatch",
        "analytics.matches_summary": "共 {ticks} ticks · 检测到 {matches} 场比赛",
        "analytics.no_data": "无数据",
        "analytics.select_match": "场次",
        "analytics.match_all": "全部场次（合并）",
        "analytics.match_live": "进行中",
        "analytics.viewing_match": "当前：{label}",
        "analytics.match_data": "比赛数据",
        "analytics.match_prev": "◀ 上一场",
        "analytics.match_next": "下一场 ▶",
        "analytics.final_score": "比分",
        "analytics.possession": "控球率",
        "analytics.territory": "球在对方半场",
        "analytics.goals": "进球时间线",
        "analytics.goal_us": "我方",
        "analytics.goal_opp": "对方",
        "analytics.goal_scorer": "疑似 {pos}",
        "analytics.no_goals": "暂无进球记录",
        "analytics.our_shots": "射门尝试",
        "analytics.select_match_hint": "选择单场比赛查看比分与进球详情",
        "analytics.result_win": "胜",
        "analytics.result_loss": "负",
        "analytics.result_draw": "平",
        "analytics.match_list": "近期比赛",
        "analytics.pick_match": "查看",
        "analytics.no_logs": "无 CloudWatch 日志",
        "analytics.grind_only_hint": "仅有 Portal 比分（日志尚未同步到 CloudWatch）",
        "settings.title": "⚙ 设置",
        "settings.aws_heading": "AWS CLI 凭证",
        "settings.aws_desc": "写入本机 ~/.aws/credentials（仅 localhost 可访问）。Workshop 临时凭证需填写 Session Token。",
        "settings.profile": "Profile",
        "settings.access_key": "Access Key ID",
        "settings.secret_key": "Secret Access Key",
        "settings.session_token": "Session Token（可选）",
        "settings.region": "默认 Region",
        "settings.save": "保存凭证",
        "settings.test": "测试连接",
        "settings.saved": "已保存到 ~/.aws/credentials",
        "settings.test_ok": "连接成功",
        "settings.test_fail": "连接失败",
        "settings.current": "当前状态",
        "settings.path": "凭证文件",
        "settings.account": "Account",
        "settings.arn": "ARN",
        "settings.valid": "有效",
        "settings.invalid": "无效 / 未配置",
        "settings.required": "请填写 Access Key ID 和 Secret Access Key",
        "settings.lang_heading": "语言 / Language",
        "settings.data_heading": "CloudWatch 数据",
        "settings.data_desc": "从 CloudWatch Logs Insights 拉取 DECISION 日志，保存到本地 cloudwatch_logs/，并下载 JSONL 文件。",
        "settings.data_prefix": "日志组前缀",
        "settings.data_minutes": "时间范围",
        "settings.data_download": "下载 CloudWatch 数据",
        "settings.data_downloading": "正在查询 CloudWatch（可能需要 1–3 分钟）…",
        "settings.data_ok": "已下载 {rows} 条（CloudWatch {cloud} 条，新保存 {saved} 条）",
        "settings.data_fail": "下载失败",
        "settings.data_local": "本地缓存",
        "settings.data_local_rows": "{rows} 条",
        "settings.data_local_files": "{files} 个文件",
        "settings.data_local_range": "{oldest} → {newest}",
        "settings.data_local_empty": "暂无本地缓存",
        "error.auth": "AWS 凭证过期或无效。请从 Workshop 重新获取凭证，在「设置」页保存，或编辑 ~/.aws/credentials。若终端仍 export 旧 AWS_* 环境变量，请重启 dashboard。",
    },
    "en": {
        "nav.observability": "Observability",
        "nav.analytics": "Analytics",
        "nav.settings": "Settings",
        "lang.toggle": "中文",
        "common.refresh": "Refresh",
        "common.loading": "Loading…",
        "common.updated": "Updated",
        "common.error": "Query error",
        "common.minutes": "min",
        "common.shots": "shots",
        "dash.title": "Football Agents Observability",
        "dash.analytics_link": "Analytics →",
        "dash.source.cloud": "Live (CloudWatch)",
        "dash.source.local": "Training ground (local)",
        "dash.source.both": "Compare: live vs training",
        "dash.minutes.15": "Last 15 min",
        "dash.minutes.30": "Last 30 min",
        "dash.minutes.60": "Last 60 min",
        "dash.minutes.180": "Last 3 hours",
        "dash.empty": "No data — Live: play a match or widen the time window; Training: run training_ground.py.",
        "dash.lat_chart": "LLM latency over time (ms, by position; dashed = 900ms timeout risk)",
        "dash.cmd_chart": "Command mix (team)",
        "dash.cmd_compare": "Command mix compare (% of ticks)",
        "dash.llm_decisions": "LLM decisions",
        "dash.shot_discipline": "Shot discipline",
        "dash.override_fixes": "Code overrides",
        "dash.healthy": "Healthy — no recommendations",
        "dash.live_vs_train": "Live vs training",
        "dash.live": "Live",
        "dash.train": "Training",
        "dash.shoot_pct": "Shoot %",
        "dash.discipline_pct": "Shot discipline %",
        "dash.move_pct": "MOVE_TO %",
        "dash.llm_pct": "LLM %",
        "dash.time_axis": "Match/training time (s)",
        "dash.compare_hint": "Live shoot rate {n} pp below training — check live state injection (hasBall/TACTICS) or pressure decisions",
        "analytics.title": "⚽ Match Analytics",
        "analytics.back": "← Observability",
        "analytics.minutes.60": "60 min",
        "analytics.minutes.180": "3 hours",
        "analytics.minutes.360": "6 hours",
        "analytics.minutes.720": "12 hours",
        "analytics.refresh_data": "Refresh data",
        "analytics.advise": "AI tuning advice",
        "analytics.heatmap": "Pitch activity heatmap",
        "analytics.samples": "samples",
        "analytics.player_stats": "Player stats",
        "analytics.team_overview": "Team overview",
        "analytics.player_analysis": "{pos} analysis",
        "analytics.legend": "Logical pitch {len}×{wid} (x±55 y±30){er} · map: x×{sx} y×{sy} · left = own goal",
        "analytics.own_goal": "Own x=-55",
        "analytics.opp_goal": "Opp x=+55",
        "analytics.avg_pos": "Avg position",
        "analytics.dist_own": "Dist to own goal",
        "analytics.dist_opp": "Dist to opp goal",
        "analytics.zone_split": "Half split",
        "analytics.zone_own": "Own half",
        "analytics.zone_opp": "Attacking",
        "analytics.shot_discipline": "Shot discipline",
        "analytics.override_fixes": "Code overrides",
        "analytics.llm_ratio": "LLM share",
        "analytics.latency_p95": "p95 latency",
        "analytics.cmd_dist": "Command mix",
        "analytics.times": "times",
        "analytics.advice_placeholder": "Click “AI tuning advice” (top right) — ~20–40s, requires Bedrock access",
        "analytics.advice_running": "AI analysis running (~20–40s)…",
        "analytics.advice_failed": "Analysis failed",
        "analytics.advice_no_pos": "No AI advice for this position (incomplete model response)",
        "analytics.advice_no_team": "No team summary",
        "analytics.model": "Model",
        "analytics.prompt_changes": "Prompt changes",
        "analytics.tuning_changes": "tuning.json",
        "analytics.code_changes": "Code (lib/)",
        "analytics.match_ticks": "{score} · {ticks}t · {shots} shots",
        "analytics.querying": "Querying CloudWatch…",
        "analytics.loading_local": "Loading local cache…",
        "analytics.local_cache_hint": "Local cache · click Refresh to sync CloudWatch",
        "analytics.matches_summary": "{ticks} ticks · {matches} matches detected",
        "analytics.no_data": "No data",
        "analytics.select_match": "Match",
        "analytics.match_all": "All matches (merged)",
        "analytics.match_live": "live",
        "analytics.viewing_match": "Viewing: {label}",
        "analytics.match_data": "Match data",
        "analytics.match_prev": "◀ Previous",
        "analytics.match_next": "Next ▶",
        "analytics.final_score": "Score",
        "analytics.possession": "Possession",
        "analytics.territory": "Ball in opp half",
        "analytics.goals": "Goal timeline",
        "analytics.goal_us": "Us",
        "analytics.goal_opp": "Opp",
        "analytics.goal_scorer": "likely {pos}",
        "analytics.no_goals": "No goals recorded",
        "analytics.our_shots": "Shot attempts",
        "analytics.select_match_hint": "Select a single match for score & goal details",
        "analytics.result_win": "W",
        "analytics.result_loss": "L",
        "analytics.result_draw": "D",
        "analytics.match_list": "Recent matches",
        "analytics.pick_match": "View",
        "analytics.no_logs": "No CloudWatch logs",
        "analytics.grind_only_hint": "Portal score only (logs not yet in CloudWatch)",
        "settings.title": "⚙ Settings",
        "settings.aws_heading": "AWS CLI credentials",
        "settings.aws_desc": "Writes to ~/.aws/credentials on this machine (localhost only). Workshop temp creds need Session Token.",
        "settings.profile": "Profile",
        "settings.access_key": "Access Key ID",
        "settings.secret_key": "Secret Access Key",
        "settings.session_token": "Session Token (optional)",
        "settings.region": "Default region",
        "settings.save": "Save credentials",
        "settings.test": "Test connection",
        "settings.saved": "Saved to ~/.aws/credentials",
        "settings.test_ok": "Connection OK",
        "settings.test_fail": "Connection failed",
        "settings.current": "Current status",
        "settings.path": "Credentials file",
        "settings.account": "Account",
        "settings.arn": "ARN",
        "settings.valid": "Valid",
        "settings.invalid": "Invalid / not configured",
        "settings.required": "Access Key ID and Secret Access Key are required",
        "settings.lang_heading": "Language / 语言",
        "settings.data_heading": "CloudWatch data",
        "settings.data_desc": "Pull DECISION logs from CloudWatch Logs Insights, save to cloudwatch_logs/, and download a JSONL file.",
        "settings.data_prefix": "Log group prefix",
        "settings.data_minutes": "Time window",
        "settings.data_download": "Download CloudWatch data",
        "settings.data_downloading": "Querying CloudWatch (may take 1–3 min)…",
        "settings.data_ok": "Downloaded {rows} rows (CloudWatch {cloud}, {saved} newly saved)",
        "settings.data_fail": "Download failed",
        "settings.data_local": "Local cache",
        "settings.data_local_rows": "{rows} rows",
        "settings.data_local_files": "{files} files",
        "settings.data_local_range": "{oldest} → {newest}",
        "settings.data_local_empty": "No local cache yet",
        "error.auth": "AWS credentials expired or invalid. Refresh Workshop creds, save on Settings, or edit ~/.aws/credentials. Restart the dashboard if the terminal still exports stale AWS_* env vars.",
    },
}

SHARED_STYLES = """
  .nav-links { display:flex; gap:12px; align-items:center; }
  .nav-links a { color:var(--accent); font-size:13px; text-decoration:none; }
  .nav-links a.active { font-weight:600; text-decoration:underline; }
  .lang-btn { background:transparent; border:1px solid var(--line,var(--border)); padding:4px 8px;
              font-size:12px; border-radius:6px; cursor:pointer; color:var(--dim); }
  .lang-btn:hover { color:var(--text); border-color:var(--accent); }
"""

I18N_SCRIPT = """
const I18N = """ + json.dumps(STRINGS, ensure_ascii=False) + """;
const LANG_KEY = "observe_lang";
let lang = localStorage.getItem(LANG_KEY) ||
  (navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en");

function t(key, vars) {
  let s = (I18N[lang] && I18N[lang][key]) || (I18N.en && I18N.en[key]) || key;
  if (vars) for (const [k,v] of Object.entries(vars)) s = s.replaceAll("{"+k+"}", v);
  return s;
}

function setLang(next) {
  lang = next;
  localStorage.setItem(LANG_KEY, lang);
  applyI18n();
  if (typeof onLangChanged === "function") onLangChanged();
}

function toggleLang() {
  setLang(lang === "zh" ? "en" : "zh");
}

function applyI18n() {
  document.documentElement.lang = lang === "zh" ? "zh" : "en";
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  const lb = document.getElementById("langBtn");
  if (lb) lb.textContent = t("lang.toggle");
}
"""


def nav_header(active: str = "") -> str:
    """HTML fragment: nav links + lang toggle."""
    def link(href: str, key: str) -> str:
        cls = ' class="active"' if active == key else ""
        return f'<a href="{href}" data-i18n="nav.{key}"{cls}></a>'

    return f"""
  <nav class="nav-links">
    {link("/", "observability")}
    {link("/analytics", "analytics")}
    {link("/settings", "settings")}
    <button type="button" class="lang-btn" id="langBtn" onclick="toggleLang()" title="Language">EN</button>
  </nav>"""
