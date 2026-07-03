# AI Team (Strands + Memory) — Per-Position Soccer Agents with AgentCore Memory

Five AI agents that each control a single player in a 5v5 soccer match, built with
[Strands Agents SDK](https://github.com/strands-agents/sdk-python) and
[Amazon Bedrock AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/) for
cross-tick history recall.

## What's Different from the Balanced Team?

Each agent uses `AgentCoreMemorySessionManager` (STM) to persist conversation history
across game ticks. This lets agents recall opponent movement patterns, previous
tactical decisions, and game flow from earlier in the match.

Key differences:
- `memory.mode: STM_AND_LTM` in AgentCore config
- `AgentCoreMemorySessionManager` wired into each Strands Agent
- System prompts instruct agents to leverage recalled history
- Requires `MEMORY_ID` environment variable (created once per deployment)

## Latency/Win-rate Tuning (this fork)

Raw history replay is slow and low-signal, so memory is split into two layers:

- **Short window (STM)**: `SlidingWindowConversationManager` keeps only the last
  ~5 ticks in context; `batch_size=2` merges each tick's user+assistant pair into
  one Memory write instead of two synchronous calls.
- **Match-long patterns**: `lib/pattern_tracker.py` accumulates opponent stats
  in-process (main ball carrier, favored attacking side, their GK's usual outlet,
  score situation) and injects a <=4-line SCOUTING REPORT into every prompt.
  Zero network calls, zero context growth.
- All agents run Nova Micro with `temperature=0.2`, `max_tokens=200`, and the
  aggressive team's compressed prompts (+ memory usage instructions).
- `MATCH_TAG` env var (optional) isolates sessions per match so one match's
  history cannot pollute the next; `TEAM_ID` scopes actor/session ids.

## Architecture

```
agents/
├── lib/                        # Shared library (same as other teams)
└── ai-team-strands-memory/
    ├── ai-gk/                  # Goalkeeper  (player 0) — Nova Micro + Memory
    ├── ai-def/                 # Defender    (player 1) — Nova Lite  + Memory
    ├── ai-mid/                 # Midfielder  (player 2) — Nova Pro   + Memory
    ├── ai-fwd1/                # Forward 1   (player 3) — Nova Micro + Memory
    ├── ai-fwd2/                # Forward 2   (player 4) — Nova Lite  + Memory
    ├── deploy-all.sh           # Build + deploy script
    └── README.md
```

## Prerequisites

- Same as the balanced team (Python 3.10+, AWS CLI, AgentCore CLI)
- A Bedrock AgentCore Memory resource (created once via `create_memory.py`)

## Quick Start

### 1. Create the Memory resource (one-time)

```bash
export AWS_DEFAULT_REGION=us-east-1
python3 create_memory.py
# Note the MEMORY_ID printed — set it as env var or in AgentCore config
```

### 2. Deploy

```bash
export MEMORY_ID=<your-memory-id>
AWS_DEFAULT_REGION=us-east-1 ./deploy-all.sh
```

### 3. Local test

```bash
python3 ai-gk/test_local.py
python3 ai-gk/test_local.py --llm  # needs AWS credentials + MEMORY_ID
```
