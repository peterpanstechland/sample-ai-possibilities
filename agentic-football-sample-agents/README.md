# Agentic Football — 环境安装指南

本仓库包含多支 AI 足球队（Strands Agents + Amazon Bedrock AgentCore）。按本文完成环境配置后，即可本地测试或部署到 AWS。

> **目录说明**：以下所有命令均假设你已在 `agentic-football-sample-agents` 目录下执行。若出现「找不到文件」错误，请先进入该目录：
>
> ```bash
> cd ~/sample-ai-possibilities/agentic-football-sample-agents
> ```
>
> Windows PowerShell：
>
> ```powershell
> cd C:\Users\<你>\Documents\robomon\sample-ai-possibilities\agentic-football-sample-agents
> ```

---

## 安装前提条件

| 工具 | 版本要求 | 用途 |
|------|----------|------|
| Python | 3.10+ | 运行 agent 与本地测试 |
| AWS CLI | v2 | 认证、部署、调用 Bedrock |
| uv | 最新版 | **部署必需** — 为 AgentCore Linux ARM64 Runtime 交叉编译 Python 依赖 |
| Strands Agents | `strands-agents` | Agent SDK |
| AgentCore CLI | `bedrock-agentcore-starter-toolkit` | 本地开发与部署 |

---

## 1. 安装基础工具

### macOS / Linux

```bash
# 安装 uv（快速 Python 包管理器）
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env" 2>/dev/null || source "$HOME/.cargo/env" 2>/dev/null

# 安装 AWS CLI（若未安装）
# macOS:  brew install awscli
# Linux:  见 https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
```

### Windows

```powershell
# 安装 uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 安装 AWS CLI
winget install Amazon.AWSCLI
```

安装 AWS CLI 后，**请新开一个终端窗口**，或手动刷新 PATH：

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
```

验证：

```bash
python3 --version   # 或 python --version
aws --version
uv --version
```

---

## 2. 创建虚拟环境并安装 Python 依赖

```bash
# 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装 Strands Agents 与 AgentCore CLI：

```bash
pip install strands-agents bedrock-agentcore-starter-toolkit
```

安装 agent 项目依赖（以 balanced 队守门员为例，其他队伍结构相同）：

```bash
pip install -r ai-team-strands-balanced/ai-gk/requirements.txt
```

验证：

```bash
agentcore --help
pip show strands-agents bedrock-agentcore-starter-toolkit
```

---

## 3. 配置 AWS 凭证

Agent 会调用 **Amazon Bedrock**，因此需要有效的 AWS 临时凭证。

### 从 AWS Workshop Studio 获取凭证

1. 打开 Workshop Studio 活动页面（左侧导航：**第一阶段：构建你的团队 → 设置和测试**）。
2. 在左侧 **AWS account access** 区域，点击 **Get AWS CLI credentials**。
3. 复制页面提供的凭证命令，粘贴到终端执行。

页面会给出类似下面的命令（**每次凭证都会不同，且会过期**）：

**macOS / Linux（bash）：**

```bash
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="ASIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
```

**Windows PowerShell：**

```powershell
$Env:AWS_DEFAULT_REGION="us-east-1"
$Env:AWS_ACCESS_KEY_ID="ASIA..."
$Env:AWS_SECRET_ACCESS_KEY="..."
$Env:AWS_SESSION_TOKEN="..."
```

**Windows CMD：**

```cmd
set AWS_DEFAULT_REGION=us-east-1
set AWS_ACCESS_KEY_ID=ASIA...
set AWS_SECRET_ACCESS_KEY=...
set AWS_SESSION_TOKEN=...
```

> **注意**
> - 凭证以 `ASIA` 开头并带有 `SESSION_TOKEN`，属于 **STS 临时凭证**，通常几小时后失效，需重新从 Workshop 获取。
> - 请勿将凭证提交到 Git 或分享给他人。
> - 若希望持久保存（仅限本机开发），可写入 `~/.aws/credentials` 和 `~/.aws/config`，或使用用户级环境变量。

### 验证凭证

```bash
aws sts get-caller-identity
```

成功时应返回 Account、Arn 等信息，例如：

```json
{
    "Account": "807965839933",
    "Arn": "arn:aws:sts::807965839933:assumed-role/WSParticipantRole/Participant"
}
```

---

## 4. 验证完整环境

在虚拟环境已激活、凭证已配置的前提下，依次检查：

```bash
# 工具链
python --version          # >= 3.10
aws --version
uv --version
agentcore --help

# AWS 认证
aws sts get-caller-identity

# 本地测试（不需要 AWS）
python ai-team-strands-balanced/ai-gk/test_local.py

# 真实 LLM 调用（需要 AWS + Bedrock 权限）
python ai-team-strands-balanced/ai-gk/test_local.py --llm
```

---

## 5. 部署到 AgentCore

部署前请确认：

- [ ] AWS 凭证有效且区域为 `us-east-1`
- [ ] 账号已开通 Bedrock 模型访问（Nova Micro / Lite / Pro）
- [ ] 已安装 `zip` 和 `rsync`（见下方各平台说明）
- [ ] **Windows 用户强烈建议用 WSL 部署**（见下文「Windows 踩坑记录」）

### macOS / Linux（推荐）

```bash
source .venv/bin/activate
cd ai-team-strands-balanced
AWS_DEFAULT_REGION=us-east-1 ./deploy-all.sh        # 部署全部 5 个 agent
AWS_DEFAULT_REGION=us-east-1 ./deploy-all.sh ai-gk  # 仅部署守门员
```

### Windows（推荐：WSL + deploy-wsl.sh）

在 Windows 上，**不要用 PowerShell 直接跑 `deploy-all.ps1`**。实测会遇到 zip 路径反斜杠、Windows `uv.exe` 无法读 WSL 路径等问题。请用项目根目录的 **`deploy-wsl.sh`** 一键脚本：

**1. 安装 WSL 依赖（首次）**

```bash
sudo apt update
sudo apt install -y zip rsync python3-venv python3-pip
```

**2. 安装 Windows 版 zip（Chocolatey，可选但建议）**

```powershell
# 管理员 PowerShell
choco install zip -y
```

**3. 部署**

```powershell
# 在项目根目录 agentic-football-sample-agents 下执行
wsl bash /mnt/c/Users/<你>/Documents/robomon/sample-ai-possibilities/agentic-football-sample-agents/deploy-wsl.sh

# 选择队伍：balanced（默认）/ aggressive / memory
wsl bash .../deploy-wsl.sh aggressive
wsl bash .../deploy-wsl.sh memory          # Memory 队（首次会自动创建 Memory 资源）

# 仅部署单个 agent
wsl bash .../deploy-wsl.sh ai-gk
wsl bash .../deploy-wsl.sh memory ai-gk
```

`deploy-wsl.sh` 会自动完成：

- 创建 `.tools/bin/aws` wrapper，让 WSL 调用 Windows 版 AWS CLI
- 安装 **Linux 版 uv**（`$HOME/.local/bin/uv`），避免 Windows `uv.exe` 读不了 `/mnt/c` 路径
- 创建 `.venv-linux` 并安装 `bedrock-agentcore-starter-toolkit`
- 调用 `ai-team-strands-balanced/deploy-all.sh` 完成打包与部署

> 若你的 AWS 配置文件不在 `C:\Users\<你>\.aws\`，需编辑 `deploy-wsl.sh` 中的 `AWS_CONFIG_FILE` / `AWS_SHARED_CREDENTIALS_FILE` 路径。

### Windows（备选：PowerShell，不推荐）

```powershell
choco install zip -y   # 管理员 PowerShell
.\.venv\Scripts\Activate.ps1
cd ai-team-strands-balanced
$env:AWS_DEFAULT_REGION = "us-east-1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
.\deploy-all.ps1
```

此方式可能仍因 zip 内路径为反斜杠导致 AgentCore 找不到 `src/main.py`，仅作备用。

### 部署成功后：获取 Agent ARN

1. 打开 **Amazon Bedrock 控制台** → **AgentCore** → **Runtime**
2. 点击每个 agent，复制 **Runtime ARN**
3. 保存全部 **5 个 ARN**，在 Workshop **Player Portal → My Team** 页面注册，才能参加比赛

示例（`ai-team-strands-balanced` 队）：

| 位置 | Runtime ARN |
|------|-------------|
| GK | `arn:aws:bedrock-agentcore:us-east-1:<账号>:runtime/ai_gk_agent-...` |
| DEF | `arn:aws:bedrock-agentcore:us-east-1:<账号>:runtime/ai_def_agent-...` |
| MID | `arn:aws:bedrock-agentcore:us-east-1:<账号>:runtime/ai_mid_agent-...` |
| FWD1 | `arn:aws:bedrock-agentcore:us-east-1:<账号>:runtime/ai_fwd1_agent-...` |
| FWD2 | `arn:aws:bedrock-agentcore:us-east-1:<账号>:runtime/ai_fwd2_agent-...` |

---

## 仓库结构

```
agentic-football-sample-agents/
├── lib/                              # 共享库（所有队伍共用）
├── docs/
│   └── OBSERVABILITY.md              # 观测台 / Analytics 部署指南（推荐阅读）
├── observe_dashboard.py              # 本地 Web 观测台 + Analytics + Settings
├── analyze_match.py                  # CLI 比赛日志分析
├── grind_matches.py                  # 批量 Portal 练习赛
├── portal_bot.py                     # Portal Playwright 自动化
├── autopilot.py                      # 自动迭代（约赛→分析→调参→部署）
├── requirements-observability.txt  # 观测台 / 门户工具依赖
├── .env.example                      # 环境变量模板（复制为 .env，勿提交）
├── screenshot/                       # 观测台界面截图（中/英）
├── deploy-wsl.sh                     # Windows 推荐：WSL 一键部署脚本
├── ai-team-strands-balanced/
│   ├── deploy-all.sh                 # macOS / Linux / WSL 部署脚本
│   └── deploy-all.ps1                # Windows PowerShell（不推荐）
├── ai-team-strands-extremely-aggressive/
├── ai-team-strands-extremely-defensive/
├── ai-team-strands-gateway/
├── ai-team-strands-memory/
└── README.md                         # 本文件
```

每支队伍包含 5 个 agent（`ai-gk`、`ai-def`、`ai-mid`、`ai-fwd1`、`ai-fwd2`），详见各队目录下的 `README.md`。

---

## 比赛观测（Observability）

> **完整部署说明**（环境变量、页面功能、批量约赛、常见问题）见 **[docs/OBSERVABILITY.md](docs/OBSERVABILITY.md)**。

Agent 每个 tick 会向 CloudWatch Logs 写一条结构化 `DECISION` 日志。本仓库提供 **本地 Web 观测台**（无需额外部署到 AWS）：

| 页面 | URL | 功能 |
|------|-----|------|
| 观测台 | http://localhost:8777/ | 实战 / 训练场 / 对比：延迟、射门、指令分布 |
| 比赛分析 | http://localhost:8777/analytics | 按场比分、热力图、AI 调参建议（中/英） |
| 设置 | http://localhost:8777/settings | AWS 凭证、CloudWatch 数据下载 |

### 快速开始

```powershell
pip install -r requirements-observability.txt
copy .env.example .env          # 填入 Workshop AWS 凭证
$env:AWS_DEFAULT_REGION = "us-east-1"
.\.venv\Scripts\python.exe observe_dashboard.py --prefix agg_ --minutes 180 --port 8777
```

- 默认读本地 `cloudwatch_logs/` 缓存；点 **Refresh data** 才同步 CloudWatch。
- 场次列表结合 `grind_results.jsonl` 时间窗切分；无日志的场次显示 Portal 比分。
- 批量约赛：`python grind_matches.py --count 10 --bot aggressive`（需 Playwright + 队伍码）。

### 命令行报告

```powershell
.venv\Scripts\python analyze_match.py --minutes 180 --prefix agg_
```

### 本地训练场（不用部署就能测策略）

```powershell
.venv\Scripts\python training_ground.py          # 只跑规则 fallback，免费
.venv\Scripts\python training_ground.py --llm    # 真实调用 Nova Micro（需要 AWS 凭证）
```

把 5 个 agent 灌入约 23 个典型场景，产出与实战同格式的 DECISION 日志（写入 `training_logs/*.jsonl`）。
观测台切到「训练场」或「对比：实战 vs 训练」查看差异。

### 实时调整队员（教练指令）

比赛过程中在 Player Portal 发送的 teamChat 消息会作为 `COACH ORDER` 注入所有 agent 的提示词，
优先级高于既定战术——比如打字「全员压上，多射门」即可实时改变全队行为，不需要重新部署。
也可通过 `portal_bot.py coach` 自动场边教练（见下文 Autopilot 一节）。

---

## 五人协同（无消息通道的编排）

平台上 5 个 agent 各自独立运行、互相不能通信。协同的实现方式是**约定式编排**：
所有 agent 从同一份 game state 用同一条确定性规则推导分工，天然达成一致：

- **自由球**：只有全队离球最近的那名球员收到「ASSIGNMENT: 你去追」，其余人收到「P{n} 去追，你保持站位/跑位」——不再出现五人抢一球；
- **对方持球**：离球最近者是「指定逼抢人」，其余人被指示去封传球线路/盯防接应点；
- **残局策略**：比赛 200 秒后按比分自动注入 `GAME PLAN`（落后=全员压上赌进攻；领先=保持阵型稳妥出球；平局=高位逼抢抢绝杀）；
- **进攻跑位**（提示词层）：一名前锋持球时另一名前锋插远门柱抢补射，中场在禁区弧顶拖后接第二点，后卫回收到中圈当安全阀。

另有**指令护栏**（`lib/parsing.py`）：LLM 输出的坐标越界自动收进场内、射门力量钳到 (0,1]、
非法瞄准点归一为 CENTER、传给自己/不存在的队友自动改传前锋——坏输出不再浪费一个 tick。

## 射门决策（LANE 检测 + 角球瞄准）

早期版本让所有位置只朝 y=0（正中）射门，全队跑到禁区中央被对方后卫直接堵死。iter-7 起
`lib/tactics.py` 的 `_shot_line` 会：

1. 在 CENTER/TL/TR/BL/BR 五个瞄准点里挑一条**通道最开**的射门线，直接给出 `SHOOT aim <X> power 1.0`；
2. 五角全被封时，判断距离——`dist<=15` 直接近距离全力 CENTER 硬射（对方脚下也能穿过），
   否则给出**横向微调 MOVE_TO**（1 tick 侧步）＋下一 tick 再射；
3. 所有五个 agent 提示词只要照 TACTICS Shot 那行的动词做，**每次持球必产出一次射门/横移**，
   不再出现「刷 SHOOT 120 次却只有 6 次真射到框」的问题；
4. Fallback 也全员打开射门（DEF `possession_action="SHOOT_OR_PASS"`），GK 拿球进入 45 内也射。

## 减少无脑逼抢

真实赛后统计里 `PRESS_BALL` 一场刷了 194–242 条，全队一起冲球，防线露出空档。iter-7 起
`FallbackConfig` 增加 `press_only_if_designated=True` 和 `off_ball_action="MARK"`：
只有离球最近的那名队员会 PRESS，其余人自动切换到 MARK（对方最近球员盯防）或保持站位。
在训练场 46 tick 里 PRESS 从平均 ~40 降到 5，MARK 出现 2 次，DEF/MID 保持阵型稳定。

## 边路进攻，不往中间挤

前锋提示词里的默认位置和 `advance_y` 从 y=±8 拉到 **y=±14**（左/右边路）；持球远离禁区时
`MOVE_TO` 目标是「opp_goal_x*0.75, y=±14」的边路空当，而不是正中的后卫堆。
另有明确规则「Do NOT run down the center, that is a defender highway」。

## 战术硬约束（Post-LLM Overrides，iter-8）

iter-7 之后的实战数据显示：LLM 应答率 100%（fallback 从不触发），于是所有只写在
提示词/fallback 里的规则对 Nova Micro 都是「可选项」——一场比赛 370 条指令里
MOVE_TO 207 条、PRESS 101 条、**MARK 0 条**。iter-8 引入 `lib/overrides.py`：
LLM 输出解析完成后，代码按游戏状态**强制改写**违反战术的指令（提示词负责引导，代码负责兜底）：

| 规则 | 触发条件 | 改写结果 |
|------|----------|----------|
| `shoot` | 持球、距门 ≤45、有清晰射门通道（或 ≤15 贴脸） | 无论 LLM 说什么，强制 `SHOOT aim <最开的角> power 1.0` |
| `aim`   | LLM 射了被封死的角 | 瞄准点改成计算出的空当角 |
| `no-chase` | 非指定逼抢人却 PRESS/追球 | 改成 `MARK` 最近的接应对手（排除持球人），或回收紧凑防线 |
| `anchor` | 防守阶段 MOVE_TO 偏离「随球移动的紧凑防线锚点」>12 | 改成盯人/回锚点——后卫线跟着球横移，不再乱跑 |
| `support` | 队友持球时输出 PRESS/PASS/SHOOT 等废指令 | 改成插入远门柱/弧顶的支援跑位 |
| `wing` | 前锋持球出射程还往中路带 | 目标 y 改到边路（±14） |

- 锚点公式随球移动：DEF `x=ball_x−12`（钳在本方 6~45 区间）、MID `x=ball_x−5`、FWD 保持高位但内收 y=±10 —— 防线紧凑性由代码保证；
- GK（player 0）豁免；只有传了 `OverrideConfig` 的球队启用（当前仅 extremely-aggressive），其他队伍行为不变；
- 每次改写都会写进 DECISION 日志的 `ov` 字段：`analyze_match.py` 输出 overrides 统计，前端 agent 卡片显示「代码纠偏」计数（悬停看明细）——下一场就能量化 LLM 与战术的偏差。

## 防守反击 + GK/DEF 无限制射门（iter-9）

对进攻型 bot 连败后拉了 4 小时 CloudWatch 日志分析（`_loss_analysis.py`），输球模式非常清晰：

- **控球困死本方半场**：拿球时距对方球门中位数 55–58，4 小时里进入射程（≤45）的 tick 只有 4 个——赢下球权却运不出来；
- **恐慌远射**：150 次射门里 112 次（75%）在 45 以外，等于白送球权；
- **幻影射门**：LLM 在没持球的 tick 也输出 SHOOT/PASS，浪费防守回合；
- **GK 高频扑救**：持续被压着打。

iter-9 的回答是把「对方压上 → 我们打身后」变成代码级流程：

| 规则 | 触发条件 | 改写结果 |
|------|----------|----------|
| `blast` | **GK/DEF 持球（开放局面）** | 无论 LLM 说什么，强制 `SHOOT power 1.0` 瞄最开的角——**没有距离限制**：最差是 60 单位的解围，最好直接进球（用户规则：门将后卫拿球直接大力射门）。定位球（GOAL_KICK 等）保留原有开球机制 |
| `longshot` | 持球距门 45–52、**对方 GK 离门 ≥12**、通道干净 | 强制吊射空门 `SHOOT power 1.0`——对方门将压上时唯一值得打的远射 |
| `counter` | 对方 ≥3 人压进我方半场时深位持球乱带，或射程外恐慌开炮 | 改成 **ONE fast `PASS type THROUGH`** 给最靠前、传球线路干净的前锋；找不到出球点则沿边路带出 |
| `phantom` | 没持球却输出 SHOOT/PASS | 指定逼抢人改 `PRESS_BALL`，其他人改盯人/回收防线 |

配套改动：

- `state.py` 新增 `count_opponents_in_our_half()`——对方 ≥3 人过半场时状态里注入 **`OPP HIGH PRESS` 行**，提示全队进入防守反击模式（防线收紧、赢球后一脚直塞、前锋保持高位当反击出球点）；
- `tactics.py` Shot 行按位置分流：**GK/DEF 持球永远是 `BLAST — SHOOT NOW`**（无射程门槛）；MID/FWD 在 45–52 且对方 GK 离门时给 `GK OFF LINE — LONG SHOT NOW`，其余远距离明确「不要开炮，先推进到 45 内」；
- 提示词同步：GK/DEF 的 RULE #1 变成「拿球=射门」，MID 是反击出球点（一脚直塞 3/4 号），FWD 在 OPP HIGH PRESS 时**不回撤**、钉在边路高位等直塞；
- 防守反击时锚点整体下沉（DEF/MID 更靠门），但前锋锚点**抬高**——反击需要有人在前面；
- fallback 同步：DEF `possession_action="SHOOT"`（无条件全力射）；
- 回归测试 Scenario K 覆盖 blast/长射/反击直塞/幻影射门修正，训练场沿用各 agent 的 `OVERRIDE_CONFIG` 自动生效。

---

## 自动循环迭代（Autopilot + Playwright，iter-10）

「打一场 → 拉日志 → 调参 → 重新部署」的整条链路现在可以无人值守跑：

```
┌─────────┐   Playwright    ┌──────────┐   Logs Insights   ┌────────┐
│ 门户约赛 │ ──────────────> │ 等终场比分 │ ────────────────> │ KPI 分析 │
└─────────┘                 └──────────┘                   └───┬────┘
     ▲                                                         │
     │        WSL deploy-wsl.sh          lib/tuning.json       ▼
┌────┴────┐ <────────────────────── ┌──────────────────────────────┐
│ 重新部署 │                        │ 调参器（规则 / --llm-advisor）│
└─────────┘                        └──────────────────────────────┘
```

三个新组件：

| 文件 | 作用 |
|------|------|
| `portal_bot.py` | Playwright 驱动 [agentic-football.aws.dev](https://agentic-football.aws.dev/)：队伍码登录（会话持久化在 `.portal-profile/`）、`POST /practice-matches` 约 bot 练习赛（balanced=The Benchmark FC / aggressive=Total Attack United / defensive=Fort Knox Athletic）、打开真实观赛页、轮询终场比分、可发教练指令 |
| `grind_matches.py` | 连续打 N 场练习赛（无自动调参），结果写入 `grind_results.jsonl`，供 Analytics 按场切分 |
| `observe_dashboard.py` | 本地 Web 观测台 + Analytics + Settings（见 [docs/OBSERVABILITY.md](docs/OBSERVABILITY.md)） |
| `portal_bot.LiveCoach` | **AI 场边教练（比赛进行中实时喊话）**：每 10s 轮询 `/matches/{id}/narration` 实时事件流（进球带比分、射门、压迫、终场哨），按「局势 → 门户预设指令」决策后 POST `/coach-instructions`。游戏引擎会把最新教练指令注入全部 5 个 agent 的提示词（`lib/state.py` 的 COACH ORDER 顶级优先），一句话同时转向全队 |
| `lib/tuning.py` + `lib/tuning.json` | **部署期调参面**：autopilot 只改 `tuning.json`，agent 启动时叠加到各自的 `OverrideConfig` 上（global → 按位置覆盖）。所有数值被 `BOUNDS` 钳制，调参器永远写不出离谱值；文件为空 = 行为与 iter-9 完全一致 |
| `autopilot.py` | 循环编排：比赛 → `collect_kpis()`（射门纪律 / 远射浪费 / 控球高度 / 被围攻指标）→ 调参（默认规则调参器，`--llm-advisor` 让 Nova Lite 在同样的 BOUNDS 内提案）→ WSL 逐 agent 重部署（S3 超时自动重试、凭证过期立即停）→ `autopilot_history.jsonl` 记录每轮配置与结果 |

使用：

```powershell
# 一次性：安装 Playwright + Chromium
pip install playwright
python -m playwright install chromium

# 一次性：固定队伍码（无头即可，无需弹浏览器，会话可复现）
python portal_bot.py setup --team-code <你的队伍码>
# 或用环境变量固定（优先级高于保存的文件）：$Env:AAFC_TEAM_CODE="<你的队伍码>"

# 三轮自动迭代（约赛 → 分析 → 调参 → 重部署）
python autopilot.py --iterations 3

# 轮换对手 / 观看直播 / 只调参不部署 / LLM 提案
python autopilot.py --bots aggressive,defensive,balanced
python autopilot.py --once --headed
python autopilot.py --once --skip-deploy
python autopilot.py --llm-advisor

# 手动打一场看结果（退出码 0=赢）；--no-live-coach 关闭场边教练
python portal_bot.py match --bot aggressive --headed

# 场边教练单独使用（锦标赛/浏览器里手动开的比赛都适用）：
python portal_bot.py coach            # 挂到当前正在进行的比赛
python portal_bot.py coach --wait     # 赛前开启：待命等开球，自动接管
python portal_bot.py coach --forever  # 一直守场边，每场比赛自动接管

# 直接连浏览器（CDP attach，不另开无头浏览器）：
#   1) 用调试端口 + 专用配置目录启动 Chrome（Chrome 136+ 会忽略默认配置上的调试端口，必须用独立 user-data-dir）：
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:TEMP\aafc-debug" --no-first-run "https://agentic-football.aws.dev"
#   2) 队伍码已固定，该窗口无需手动登录，直接：
python portal_bot.py status --cdp             # 默认连 http://127.0.0.1:9222（注意用 IPv4，不是 localhost）
python portal_bot.py coach --forever --cdp
```

场边教练的局势 → 指令映射（门户只接受 6 个预设，自由文本会被 400 拒绝）：

| 局势 | 预设指令 | 效果（引擎注入的喊话） |
|------|---------|--------------------|
| 刚丢球（事件触发，无冷却） | `press_high` | 立刻高位反抢 |
| 刚进球领先 | `slow_the_tempo` | 稳住阵型别浪 |
| 落后（常规时间） | `shoot_on_sight` | "Why are you keeping the ball! Shoot!" |
| 落后（最后 30%时间） | `go_all_out_attack` | 全员压上死磕 |
| 领先（最后 30%时间） | `slow_the_tempo` | 收缩保胜果 |
| 平局（最后 30%时间） | `increase_the_tempo` | 提速抢胜 |
| 被围攻（30s 内对方 3+ 次射门/压迫）| `slow_the_tempo` | 稳住再反击 |

规则：进球/丢球事件绕过 45s 冷却立即喊；相同指令已生效时去重不重发；终场后 400 静默忽略。

调参器的规则沿用 iter-6→9 的手工经验：丢 3 球以上 → 提前进入反击姿态（`press_bodies -1`）+ 扩大盯人半径；远射占比 >40% → 收紧 `longshot_max`、提高 `gk_out_dist` 门槛；0 进球且射门 <8 → `shoot_threshold +2` 提前开火；控球率 <35% → 降低 `outlet_min_gain` 让解压传球更容易出脚；**赢球则冻结配置**。每一轮的 KPI、调参前后对照、部署结果都会追加到 `autopilot_history.jsonl`，这就是整个循环的「经验」。

**Iter-12b — 破高位逼抢：route-one 长传（iter-12 验证赛 0-1 数据驱动）**：iter-12 部署后对 Total Attack United 从 1-5/0-4 收窄到 **0-1**（抢断 22 次、拦截 50 次、GK 扑救 66 次，防守投诉彻底解决；教练指令排队实证生效：35s 进球→47s 中圈开球后才注入）。但暴露出三场共有的病根仍在：`in_range_ticks = 0`、`far_shot_ratio = 1.0`——全队 33 脚射门全是 GK/DEF 从 85 单位外的大脚，前锋 **0 射门**。对高位逼抢队，DEF 每次持球都被逼抢且地面出球线路全被封 → `build`/`carry` 无法触发 → 盲目大脚把球权还回去 → 前锋永远拿不到球，`cutback`/终结逻辑根本没机会激活。改动：被逼抢且地面线路全封时，不再盲目大脚，改为**向最前场的前锋起一脚过顶长传 route-one**（`ov=launch`，AERIAL）——同样的解围距离，但**瞄准的是我方球员**，绕过逼抢、把从不碰球的前锋直接送出去打反击；只有当无任何前锋处于身前时才回落到大脚。回归测试 Scenario O9/O9b，且 M2b/M3 更新为「地面封死+前锋在前 → 长传」（大脚从此近乎绝迹）。

**Iter-12 — 终结与抢断补丁（两场验证赛 1-5 / 0-4 数据 + 用户观察驱动）**：两场对 Total Attack United 的验证赛给出一致证据：全队 `in_range_ticks = 0`（持球从未进入射程）、`ov=build` 全场 0 次、SLIDE_TACKLE 每场 1-4 次 / INTERCEPT 0-2 次、GK 每场 15-17 次无球「射门」（幽灵踢空气）；用户在画面上看到的正是这些——前锋带球冲到底线丢球、往人堆里带球射门、防守只盯人不下脚。改动一揽子：(1) **cutback 终结**（`ov=cutback/sidestep`）：射程内所有射门线路被堵时不再任由 LLM 往人堆里带——传 GROUND 回做球给禁区内有空位射门线路的队友，否则按 tactics 算好的横向 sidestep 慢速移出线路；(2) **带球封顶**（`ov=cap` + `carry_cap_x=44`）：任何带球 MOVE_TO 的目标 x 被钳在禁区边缘，接近目标 12 内自动取消 sprint——1 秒状态延迟导致的冲底线过冲从此被硬性拦截；(3) **支援点回收**：前锋支援点从底线附近（距门线 7）退到点球点深度（13，y=±9），做 cutback 的接应点而不是在底线扎堆；(4) **抢断升级**（`ov=tackle/intercept`，`tackle_dist=3.5`）：被指派的逼抢者贴近持球人 3.5 内自动改写为 SLIDE_TACKLE，散球 10 以内改写为 INTERCEPT——盯人只是站位，下脚才能夺回球权；(5) **GK 扑球补丁**（`ov=gk-smother/gk-cover`）：GK 无球时的幽灵踢改写为 INTERCEPT 扑散球或回门线补位；(6) **DEF 无人逼抢且无出球线路时改带球推进**（`ov=carry`）而不是白送大脚，GK 仍保持解围；(7) **教练指令时机**：进球触发的指令改为排队，等比赛时钟越过进球点（过场动画+中圈开球结束）再注入，DECISION 日志新增 `co` 字段实证指令确实进入了球员提示词；(8) `outlet_min_gain` 12→9：更容易找到出球点。回归测试 Scenario O 全覆盖。

**Iter-11d — 进攻三人组换 Nova 2 Lite（`bench_models.py` 实测驱动）**：用真实 FWD1 提示词 + 训练场三个典型局面对 7 个 Bedrock 候选模型各跑 24 次实测（同一条生产调用链）。结论：`us.amazon.nova-2-lite-v1:0` 全绿——JSON 解析 24/24、防守局面唯一正确选 MARK、p95 反而低于 Micro（1303 vs 1484ms，中位数仅 +8%）；llama3-1-8b 中位最快但尾部肥+服从最差；claude-haiku-4.5 在 200 token 预算下频繁截断且 p95 3.1s；nova-lite v1 空数组率 38%。落地：**MID/FWD1/FWD2 切 Nova 2 Lite**（决策质量收益最大），**GK/DEF 留 Nova Micro**（行为已被 blast/build override 兜底，要的是快）。真 tool-call 路线维持不采用：两轮模型往返 + Lambda 物理上超出 1s tick 预算，工具数学继续由 `tactics_report` 进程内预计算注入提示词。

**Iter-11c — 被逼抢也要出球（1-5 验证赛数据驱动）**：iter-11 的门槛是「被逼抢（对手 ≤ `blast_pressure_dist`）就大脚」，验证赛（1-5 负 Total Attack United）暴露了盲点：对高位逼抢队，GK/DEF 每次持球必然处于被逼抢状态 → `ov=build` 全场 **0 次**触发，后场出球在最需要它的对手面前被完全关死。改为：被逼抢时**仍然找出球点，但安全走廊要求放宽 1.5 倍**（`outlet_lane_radius` ×1.5），真正无人可传才大脚——一脚干净的出球正是破解逼抢的方式。Scenario M2/M2b 覆盖「被压但有宽线路 → 出球」和「被压且全堵死 → 大脚」。

**Iter-11b — 前锋/中场进攻再平衡（锦标赛数据驱动）**：300 分钟锦标赛日志（含 0-3 负 Excalibur）显示 FWD1 射门 **0** 次、MID 2 次，三名进攻球员 80-91% 的 tick 花在 MOVE_TO+MARK 上（`anchor` 333/345、`no-chase` 327 次改写）——前锋被防守规则当后卫用，我方持球时也没人强制他们拉开。改动：(1) **我方持球时 MID/FWD 的 MARK/SET_STANCE/回撤 MOVE_TO 一律改写为支援跑位**（`ov=support`），前锋冲两侧门柱外 ±11 拉宽禁区、MID 压到禁区弧顶（x=0.6×球门），只有真正向前的跑位放行；(2) 前锋 `mark_radius` 24→16（per-position tuning）：防守时少被拖去盯远人，站高位当 build_from_back 的出球目标；(3) FWD `shoot_threshold` 48、MID 47：接球更早开火。回归测试 Scenario N 覆盖（盯人改写 / 回撤改写 / 向前跑放行 / DEF 豁免）。

**Iter-11 — build from the back（由 6 场 KPI 历史数据驱动）**：历史数据里每一场都是同一个病灶——`far_shot_ratio` 0.92-0.98（射门几乎全是 45+ 的大脚）、`in_range_ticks = 0`（全队持球时从未进入过射程内）、GK 单场 25-32 次「射门」全是解围。无脑 blast 等于每次拿球都把球权还给对手，对弱队够赢、对进攻型强队就是被打穿的根源。改动：`build_from_back`（`tuning.json` 全局开启）——GK/DEF 拿球时**若无人逼抢（最近对手 > `blast_pressure_dist`，默认 10）且有干净的向前传球线路**，改为向最前场的空位队友送出弹进空间的 THROUGH/长距离 AERIAL 出球（`ov=build`），把球喂进进攻三区；**被逼抢或无人可传时照旧 blast**（iter-9 的用户规则保持为兜底）。规则调参器在远射比过高时会自动收小 `blast_pressure_dist`（更敢出球），回归测试 Scenario M 覆盖全部分支（安全出球 / 被压 blast / 无线路 blast / 默认关闭 / 定位球豁免）。

注意：
- 门户会话（`.portal-profile/`）和历史（`autopilot_history.jsonl`）已加入 `.gitignore`，不会提交；
- 需要有效的 AWS 凭证（CloudWatch 查询在 Windows 侧、部署在 WSL 侧），过期时 autopilot 会明确报错停止而不是带病循环；
- 回归测试 Scenario L 覆盖 tuning 叠加/钳制/不可变性；训练场（`training_ground.py`）同样叠加 tuning，本地模拟与线上行为一致。

**关于「Playwright 会话和我浏览器的不一样」**：Playwright 默认用独立的 `.portal-profile/` Chromium 配置，和你日常浏览器（Chrome/Edge）的登录态天然隔离。有两种对齐方式：

1. **固定队伍码（推荐，无需浏览器）**：门户的鉴权本质就是 `Authorization: Bearer team:<队伍码>` —— 只要队伍码相同，两边就是**同一支队伍、同一批比赛记录**（记录存服务端，不跟着浏览器走）。`setup --team-code`（或设 `AAFC_TEAM_CODE`）固定一次即可：`token()` 会在 localStorage 为空/被锁/换机器时回退到这个固定码，`ensure_login` 还会把它写回 SPA 的 localStorage。
2. **直接连你自己的浏览器（`--cdp`）**：如果你想让脚本用的就是你开着的那个浏览器（同一份 cookie/localStorage/登录态），用调试端口启动 Chrome/Edge，脚本通过 `connect_over_cdp` attach 上去。`--cdp` 模式下脚本**只 attach 不关闭**你的浏览器，也不会抢占你正在看的 tab（已在门户 origin 就不重新导航）。两个 Windows 上的坑：
   - **Chrome 136+ 会忽略默认配置目录上的 `--remote-debugging-port`**（安全限制），所以必须配一个独立的 `--user-data-dir`（如 `$env:TEMP\aafc-debug`）。用独立配置也就意味着那个窗口没有你原本的登录态——但队伍码已固定，脚本靠它认证，无需手动登录。
   - **`localhost` 在 Windows 常解析成 IPv6 `::1`，而 Chrome 调试端口只监听 IPv4 `127.0.0.1`**，所以默认连 `http://127.0.0.1:9222`（`_attach_over_cdp` 里也会自动把 `localhost` 换成 `127.0.0.1`）。

---

## 常见问题

### `aws` 命令找不到

- Windows：安装后需**新开终端**，或刷新 PATH（见上文第 1 节）。
- 确认 `C:\Program Files\Amazon\AWSCLIV2\` 已在系统或用户 PATH 中。
- **WSL 内**：默认没有 `aws`，`deploy-wsl.sh` 会通过 `.tools/bin/aws` 调用 Windows 版 `aws.exe`。

### `Unable to parse config file: ~/.aws/config`

- 通常是配置文件带 **UTF-8 BOM**。用无 BOM 的编辑器重新保存，或删除后重新 `aws configure`。

### 凭证过期

- Workshop 提供的是 **STS 临时凭证**（`ASIA` 前缀 + `SESSION_TOKEN`），通常几小时后失效。
- 重新打开 Workshop Studio → **Get AWS CLI credentials** → 复制新命令执行。
- WSL 部署时 `deploy-wsl.sh` 读取 `~/.aws/credentials`（映射到 Windows 路径），更新凭证后无需改脚本。

---

## Windows 部署踩坑记录（实测）

以下是在 Windows + WSL 环境下部署 `ai-team-strands-balanced` 时遇到的全部问题及处理方式。**强烈建议直接走 `deploy-wsl.sh`，可一次性避开大部分坑。**

### 坑 1：缺少 `zip` 命令

| 现象 | `zip utility not found` |
|------|-------------------------|
| 原因 | Windows 默认没有 Info-ZIP 的 `zip.exe`，`agentcore deploy` 打包时需要 |
| 解决 | 管理员 PowerShell：`choco install zip -y`；WSL：`sudo apt install zip` |

### 坑 2：PowerShell 直接部署 — zip 内路径是反斜杠

| 现象 | `entrypoint could not be found`（`src\main.py`） |
|------|--------------------------------------------------|
| 原因 | Windows 上 `os.path.join` 产生反斜杠，打进 zip 后 AgentCore **Linux ARM64** Runtime 找不到入口 |
| 解决 | **改用 WSL 部署**（`deploy-wsl.sh`），路径为 Unix 正斜杠 |

### 坑 3：OpenTelemetry 可执行文件找不到

| 现象 | `OpenTelemetry instrumentation executable not found` |
|------|------------------------------------------------------|
| 原因 | `uv pip install --target --only-binary :all:` 交叉编译时**不会**在 `bin/` 生成 `opentelemetry-instrument` 等控制台脚本；但模板里 `observability.enabled: true` |
| 解决 | `deploy-all.sh` / `deploy-all.ps1` 已自动将生成的 `.bedrock_agentcore.yaml` 中 `enabled: true` 改为 `enabled: false` |

### 坑 4：Shell 脚本 CRLF 行尾

| 现象 | `deploy-all.sh: cannot execute`；`$'\r': command not found`；路径变成 `ai-gk\r/requirements.txt` |
|------|--------------------------------------------------------------------------------------------------|
| 原因 | 在 Windows 上编辑的 `.sh` 文件带 **CRLF**，WSL bash 会把 `\r` 当成路径的一部分 |
| 解决 | 保存为 **LF** 行尾；或在 WSL 执行：`sed -i 's/\r$//' deploy-all.sh` |

### 坑 5：WSL 里找不到 `aws`

| 现象 | `ERROR: 'aws' CLI not found` |
|------|------------------------------|
| 原因 | WSL 未单独安装 AWS CLI，且 Windows PATH 不一定透传 |
| 解决 | `deploy-wsl.sh` 自动创建 `.tools/bin/aws` → 调用 `aws.exe` |

### 坑 6：AWS Account ID 带尾随空格

| 现象 | `Invalid AWS account ID '807965839933 '` |
|------|------------------------------------------|
| 原因 | 通过 Windows `aws.exe` 取账号 ID 时，输出末尾可能带空格或 `\r` |
| 解决 | `deploy-all.sh` 已用 `tr -d ' \r\n'` 清理 |

### 坑 7：WSL 里找不到 `uv`

| 现象 | `uv is required but not found` |
|------|--------------------------------|
| 原因 | Windows 装的 `uv.exe` 不在 WSL PATH 中 |
| 解决 | `deploy-wsl.sh` 自动用 `curl ... | sh` 安装 **Linux 版 uv** 到 `$HOME/.local/bin` |

### 坑 8：Windows `uv.exe` 无法读取 `/mnt/c` 路径（最关键）

| 现象 | `Failed to install dependencies with uv: File not found: .../_build/ai-gk/requirements.txt`（文件实际存在） |
|------|-------------------------------------------------------------------------------------------------------------|
| 原因 | **Windows 版 `uv.exe` 无法正确处理 WSL 挂载的 `/mnt/c/...` 路径**；`agentcore deploy` 内部用 `shutil.which("uv")` 找 uv，若 PATH 里 Windows uv 优先，就会踩坑 |
| 解决 | ① `deploy-wsl.sh` 把 `$HOME/.local/bin`（Linux uv）放在 PATH **最前**；② 删除 `.tools/bin/uv` 等指向 `uv.exe` 的 wrapper；③ **不要**把 `/mnt/c/Users/<你>/.local/bin` 加入 WSL PATH |

验证当前用的是哪个 uv：

```bash
# 在 WSL 中，应输出 /home/<你>/.local/bin/uv，而不是 uv.exe
which uv
```

### 坑 9：`.tools/bin/uv` 残留 wrapper

| 现象 | 同坑 8，`which uv` 显示 `.tools/bin/uv` |
|------|----------------------------------------|
| 原因 | 早期调试时创建的 bash wrapper：`exec "/mnt/c/.../uv.exe"` |
| 解决 | `deploy-wsl.sh` 每次运行会 `rm -f "$TOOLS_BIN/uv"`；手动也可删除 |

### 坑 10：部署失败留下半成品资源

| 现象 | IAM Role、S3 bucket、Agent Runtime 已创建，但 endpoint 失败 |
|------|-------------------------------------------------------------|
| 原因 | 多次失败重试时 AWS 侧已有部分资源 |
| 解决 | `deploy-all.sh` 使用 `agentcore deploy --auto-update-on-conflict`，可直接覆盖重部署，一般无需手动清理 |

### 坑 11：PowerShell 控制台乱码

| 现象 | 部署日志中文/表格符号显示为乱码 |
|------|--------------------------------|
| 原因 | PowerShell 默认编码与 Python stdout 不一致 |
| 解决 | `$env:PYTHONUTF8='1'`；`$env:PYTHONIOENCODING='utf-8'`（`deploy-all.ps1` 已设置） |

### 坑 12：LLM 测试 ai-mid 偶发 JSON 解析失败

| 现象 | `test_local.py --llm` 时 ai-mid 失败，Nova Pro 返回 `sprint: True`（Python 风格）而非 `true` |
|------|------------------------------------------------------------------------------------------------|
| 原因 | 模型输出非严格 JSON；不影响部署，本地有 fallback 逻辑 |
| 解决 | 可忽略；或后续在 `lib/parsing.py` 中兼容 `True`/`False` |

### 坑 13：测试时请显式指定 venv 的 Python

| 现象 | 用了系统 Python，缺依赖或版本不对 |
|------|-----------------------------------|
| 解决 | Windows：`.\.venv\Scripts\python.exe ai-team-strands-balanced/ai-gk/test_local.py` |

### 部署方式对比（Windows）

| 方式 | 推荐度 | 主要问题 |
|------|--------|----------|
| **`deploy-wsl.sh`（WSL）** | ⭐ 强烈推荐 | 需 WSL + apt 装 zip/rsync；首次会装 Linux uv |
| `deploy-all.sh`（WSL 手动） | ⭐ 推荐 | 需自行配置 aws wrapper、Linux uv、PATH |
| `deploy-all.ps1`（PowerShell） | ⚠️ 不推荐 | zip 反斜杠、Windows uv 交叉编译等问题 |

---

## 其他常见问题

### `agentcore` 找不到

- 确认已激活 `.venv`（或 WSL 的 `.venv-linux`），且已执行 `pip install bedrock-agentcore-starter-toolkit`。

### 部署时缺少 `zip` 或 `rsync`

- Windows + WSL：`sudo apt install zip rsync`
- Windows 原生：`choco install zip -y`（仍建议改走 WSL）

---

## 环境检查清单

| 步骤 | 命令 / 操作 | 状态 |
|------|-------------|------|
| Python 3.10+ | `python --version` | ☐ |
| AWS CLI | `aws --version` | ☐ |
| uv | `uv --version` | ☐ |
| 虚拟环境 | `.venv` 已创建并激活 | ☐ |
| Strands + AgentCore | `pip install strands-agents bedrock-agentcore-starter-toolkit` | ☐ |
| 项目依赖 | `pip install -r ai-team-strands-balanced/ai-gk/requirements.txt` | ☐ |
| AWS 凭证 | Workshop → Get AWS CLI credentials | ☐ |
| 凭证验证 | `aws sts get-caller-identity` | ☐ |
| 本地测试 | `python ai-team-strands-balanced/ai-gk/test_local.py` | ☐ |
| Windows：zip | `choco install zip -y` 或 WSL `apt install zip` | ☐ |
| Windows：WSL 依赖 | `sudo apt install zip rsync python3-venv` | ☐ |
| 部署（Windows） | `wsl bash deploy-wsl.sh` | ☐ |
| 部署（macOS/Linux） | `cd ai-team-strands-balanced && ./deploy-all.sh` | ☐ |
| 注册 ARN | Workshop Player Portal → My Team | ☐ |

完成以上步骤后，环境即可用于 Workshop 后续阶段（本地开发、LLM 测试、部署）。
