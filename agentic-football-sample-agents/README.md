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

Agent 每个 tick 会向 CloudWatch Logs 写一条结构化 `DECISION` 日志（延迟、指令、决策来源、prompt 大小）。两种查看方式：

### 网页观测台（推荐）

```powershell
.venv\Scripts\python observe_dashboard.py --prefix agg_    # 打开 http://localhost:8777
```

本地网页，每 30 秒自动刷新，展示每个 agent 的：决策来源占比（LLM vs fallback）、延迟 p50/p95、**射门次数**、**把握射门**（持球进入 45 射程时真的射了几次——衡量策略是否被执行的核心指标）、指令分布、调优建议，以及全队延迟散点图。参数：`--prefix`（runtime 名前缀，如 `agg_`）、`--minutes`、`--port`、`--region`。

### 命令行报告

```powershell
.venv\Scripts\python analyze_match.py --minutes 45 --prefix agg_
```

打完一场比赛后运行，输出逐 agent 的统计与调优建议（例如「FWD1 一直在带球不射门」）。

### 本地训练场（不用部署就能测策略）

```powershell
.venv\Scripts\python training_ground.py          # 只跑规则 fallback，免费
.venv\Scripts\python training_ground.py --llm    # 真实调用 Nova Micro（需要 AWS 凭证）
```

把 5 个 agent 灌入约 23 个典型场景（开球、进攻梯度、防守、追自由球、落后/领先残局、教练指令），
产出与实战完全同格式的 DECISION 日志（写入 `training_logs/*.jsonl`）。
观测台切到「训练场」看单独数据，切到「对比：实战 vs 训练」逐位置对比射门率、MOVE_TO 率、延迟——
若实战射门率明显低于训练，通常是实战状态注入或对手压迫的问题，而不是提示词本身。

### 实时调整队员（教练指令）

比赛过程中在 Player Portal 发送的 teamChat 消息会作为 `COACH ORDER` 注入所有 agent 的提示词，
优先级高于既定战术——比如打字「全员压上，多射门」即可实时改变全队行为，不需要重新部署。

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
