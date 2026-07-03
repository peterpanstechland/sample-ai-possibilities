# Deploy all 5 AI Team agents to Bedrock AgentCore (Windows PowerShell)
#
# Usage:
#   .\deploy-all.ps1           # deploy all
#   .\deploy-all.ps1 ai-gk     # deploy one agent
#
# Prerequisites:
#   - .venv with bedrock-agentcore-starter-toolkit (agentcore CLI)
#   - AWS CLI configured
#   - zip utility in PATH (choco install zip -y, or WSL: sudo apt install zip)

param(
    [string]$Agent = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$BuildDir = Join-Path $ScriptDir "_build"
$AllAgents = @("ai-gk", "ai-def", "ai-mid", "ai-fwd1", "ai-fwd2")

if ($Agent) {
    $Agents = @($Agent)
} else {
    $Agents = $AllAgents
}

$env:AWS_DEFAULT_REGION = if ($env:AWS_DEFAULT_REGION) { $env:AWS_DEFAULT_REGION } else { "us-east-1" }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:AGENTCORE_SUPPRESS_RECOMMENDATION = "1"

# Refresh PATH for AWS CLI
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
            [Environment]::GetEnvironmentVariable("Path", "User")

$Agentcore = Join-Path $RepoRoot ".venv\Scripts\agentcore.exe"
if (-not (Test-Path $Agentcore)) {
    Write-Error "agentcore CLI not found at $Agentcore. Run: pip install bedrock-agentcore-starter-toolkit"
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Error "aws CLI not found. Install AWS CLI and refresh PATH."
}

if (-not (Get-Command zip -ErrorAction SilentlyContinue)) {
    Write-Error @"
zip utility not found (required for direct_code_deploy).

Install options:
  - WSL:  sudo apt install zip
  - Chocolatey (admin): choco install zip -y
  - Or run deploy-all.sh from WSL/Git Bash instead
"@
}

Write-Host "=========================================="
Write-Host "  AI Team — Deploy Agents (Windows)"
Write-Host "=========================================="
Write-Host ""
Write-Host "Checking prerequisites..."
Write-Host "  agentcore CLI: OK"
Write-Host "  zip: OK"
Write-Host "  aws CLI: OK"

$Account = (aws sts get-caller-identity --query Account --output text).Trim()
if (-not $Account) {
    Write-Error "No valid AWS credentials."
}
Write-Host "  AWS Account: $Account"
Write-Host "  AWS Region:  $env:AWS_DEFAULT_REGION"
Write-Host ""

$Deployed = @()
$Failed = @()

try {
    foreach ($agentName in $Agents) {
        $AgentSrc = Join-Path $ScriptDir $agentName
        $Stage = Join-Path $BuildDir $agentName

        Write-Host "=========================================="
        Write-Host "  Deploying: $agentName"
        Write-Host "=========================================="

        if (-not (Test-Path $AgentSrc)) {
            Write-Host "  ERROR: Agent directory not found: $AgentSrc"
            $Failed += $agentName
            continue
        }

        if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
        New-Item -ItemType Directory -Force -Path (Join-Path $Stage "src") | Out-Null

        Copy-Item (Join-Path $AgentSrc "src\main.py") (Join-Path $Stage "src\main.py")
        Copy-Item (Join-Path $AgentSrc "requirements.txt") (Join-Path $Stage "requirements.txt")

        $LibDest = Join-Path $Stage "lib"
        New-Item -ItemType Directory -Force -Path $LibDest | Out-Null
        Get-ChildItem (Join-Path $RepoRoot "lib") -File |
            Where-Object { $_.Name -ne "__pycache__" } |
            Copy-Item -Destination $LibDest

        $Template = Get-Content (Join-Path $AgentSrc ".bedrock_agentcore.yaml.template") -Raw
        $Yaml = $Template.Replace('${AWS_ACCOUNT_ID}', $Account).Replace('${AWS_DEFAULT_REGION}', $env:AWS_DEFAULT_REGION)
        # Windows + uv cross-compile does not install console scripts into bin/ (no opentelemetry-instrument).
        # Disable observability so the runtime entrypoint does not require OTEL executables in the zip.
        $Yaml = $Yaml -replace '(?m)(^\s+observability:\r?\n\s+enabled:\s*)true', '${1}false'
        $Utf8 = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText((Join-Path $Stage ".bedrock_agentcore.yaml"), $Yaml, $Utf8)

        Write-Host "  Deploying from: $Stage"
        Push-Location $Stage
        try {
            & $Agentcore deploy --auto-update-on-conflict
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  OK $agentName : DEPLOYED"
                $Deployed += $agentName
            } else {
                Write-Host "  FAIL $agentName : FAILED (exit $LASTEXITCODE)"
                $Failed += $agentName
            }
        } finally {
            Pop-Location
        }
        Write-Host ""
    }
} finally {
    Write-Host "Cleaning up build directory..."
    if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
}

Write-Host "=========================================="
Write-Host "  Deployment Summary"
Write-Host "=========================================="
Write-Host ""
Write-Host "  Deployed: $(if ($Deployed.Count) { $Deployed -join ' ' } else { 'none' })"
Write-Host "  Failed:   $(if ($Failed.Count) { $Failed -join ' ' } else { 'none' })"
Write-Host "  Account:  $Account"
Write-Host "  Region:   $env:AWS_DEFAULT_REGION"
Write-Host ""

if ($Failed.Count -gt 0) {
    Write-Error "Some agents failed to deploy. Check the output above."
}

Write-Host "All agents deployed successfully."
