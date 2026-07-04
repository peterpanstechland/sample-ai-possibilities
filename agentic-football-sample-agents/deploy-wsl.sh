#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOLS_BIN="$ROOT/.tools/bin"
mkdir -p "$TOOLS_BIN"

# AWS CLI wrapper (Windows exe, callable as `aws` from WSL)
cat > "$TOOLS_BIN/aws" << 'EOF'
#!/bin/bash
exec "/mnt/c/Program Files/Amazon/AWSCLIV2/aws.exe" "$@"
EOF
chmod +x "$TOOLS_BIN/aws"
# Remove stale Windows uv wrapper if present (breaks /mnt/c cross-compile)
rm -f "$TOOLS_BIN/uv"

# Linux uv (Windows uv.exe cannot read /mnt/c paths during cross-compile).
# `wsl bash -c` doesn't source .profile so ~/.local/bin is off PATH — check the
# actual binary path before doing a slow curl re-download from astral.sh.
if [ ! -x "$HOME/.local/bin/uv" ] && ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# Linux uv must come before any Windows uv.exe on PATH (Windows uv cannot read /mnt/c paths)
export PATH="$HOME/.local/bin:$TOOLS_BIN:$ROOT/.venv-linux/bin:$PATH"
export AWS_CONFIG_FILE=/mnt/c/Users/peter/.aws/config
export AWS_SHARED_CREDENTIALS_FILE=/mnt/c/Users/peter/.aws/credentials
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AGENTCORE_SUPPRESS_RECOMMENDATION=1

if [ ! -d "$ROOT/.venv-linux" ]; then
  python3 -m venv "$ROOT/.venv-linux"
  source "$ROOT/.venv-linux/bin/activate"
  pip install -q bedrock-agentcore-starter-toolkit
else
  source "$ROOT/.venv-linux/bin/activate"
fi
# Memory team needs the bedrock-agentcore SDK (MemoryClient) for create_memory.py
python3 -c "import bedrock_agentcore.memory" 2>/dev/null || pip install -q bedrock-agentcore

TEAM_DIR="${TEAM_DIR:-ai-team-strands-balanced}"
if [ "$1" = "aggressive" ] || [ "$1" = "agg" ]; then
  TEAM_DIR="ai-team-strands-extremely-aggressive"
  shift
elif [ "$1" = "memory" ] || [ "$1" = "mem" ]; then
  TEAM_DIR="ai-team-strands-memory"
  shift
elif [ "$1" = "gateway" ] || [ "$1" = "gw" ]; then
  TEAM_DIR="ai-team-strands-gateway"
  shift
elif [ "$1" = "balanced" ] || [ "$1" = "bal" ]; then
  TEAM_DIR="ai-team-strands-balanced"
  shift
fi

echo "Deploying team: $TEAM_DIR"
cd "$ROOT/$TEAM_DIR"
bash deploy-all.sh "$@"
