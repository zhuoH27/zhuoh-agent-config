# agent-config 极简入口（Windows PowerShell 5.1+ / pwsh 7）。
# 核心逻辑在 scripts/agent_sync.py（Python 3 标准库）；本文件以 UTF-8 BOM + CRLF 保存（.gitattributes）。
# 有 Python：透传参数（--verify 映射为 doctor）。
# 无 Python：裸机兜底，纯拷贝 AGENTS.md 与 skills/ 到宿主（备份后覆盖，功能受限）。
# 兼容原 v2.2.0 参数：[--dry-run|--apply|--verify] --target auto|claude|codex|agents|both
#                     --mode append|replace|abort --home 目录 --version
# 安全边界：无网络访问；不执行任意代码；备份统一存 ~/.zhuoh-agent-backup/<TS>/。

$VERSION = '3.0.0'
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) } catch {}

if ($args.Count -eq 1 -and $args[0] -eq '--version') {
    Write-Output "agent-config $VERSION (ps1)"
    exit 0
}

$Repo = $PSScriptRoot

# 定位 Python
$Py = Get-Command python -ErrorAction SilentlyContinue
if (-not $Py) { $Py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $Py) { $Py = Get-Command py -ErrorAction SilentlyContinue }

if ($Py) {
    $engine = Join-Path $Repo 'scripts\agent_sync.py'
    $sub = 'setup'
    $pass = @()
    foreach ($a in $args) {
        switch ($a) {
            '--verify' { $sub = 'doctor' }
            default    { $pass += $a }
        }
    }
    $pyArgs = if ($Py.Source -match 'py\.exe$') { @('-3') } else { @() }
    & $Py.Source @pyArgs -I $engine $sub @pass
    exit $LASTEXITCODE
}

# --- 裸机兜底（无 Python）---
Write-Output '未检测到 Python，使用裸机兜底模式（纯拷贝，功能受限）。'

$RawArgs = $args
$target = 'auto'
$homeArg = $null
$i = 0
while ($i -lt $RawArgs.Count) {
    switch ($RawArgs[$i]) {
        '--target' { $i++; $target = [string]$RawArgs[$i] }
        '--home'   { $i++; $homeArg = [string]$RawArgs[$i] }
        '--dry-run' { Write-Error '兜底模式不支持 --dry-run，请安装 Python。'; exit 1 }
        default { }
    }
    $i++
}

$realHome = if ($homeArg) {
    if ($homeArg.StartsWith('~')) { Join-Path $env:USERPROFILE $homeArg.Substring(1) } else { $homeArg }
} else { $env:USERPROFILE }

$ts = if ($env:AGENT_CONFIG_TS) { $env:AGENT_CONFIG_TS } else { Get-Date -Format 'yyyyMMdd_HHmmss' }
$broot = Join-Path $realHome ".zhuoh-agent-backup\$ts"
New-Item -ItemType Directory -Path $broot -Force | Out-Null

function Copy-Host([string]$key) {
    $root = Join-Path $realHome ".$key"
    $rulesName = if ($key -eq 'claude') { 'CLAUDE.md' } else { 'AGENTS.md' }
    $rules = Join-Path $root $rulesName
    New-Item -ItemType Directory -Path (Join-Path $root 'skills') -Force | Out-Null
    if (Test-Path $rules) {
        $bak = Join-Path $broot ("{0}_{1}.md.bak" -f $rulesName, $ts)
        Copy-Item $rules $bak
        Write-Output "备份: $rules -> $bak"
    }
    Copy-Item (Join-Path $Repo 'AGENTS.md') $rules -Force
    Write-Output "写入: $rules"
    foreach ($d in Get-ChildItem (Join-Path $Repo 'skills') -Directory) {
        $dst = Join-Path $root "skills\$($d.Name)"
        if (Test-Path (Join-Path $dst 'SKILL.md')) {
            Copy-Item (Join-Path $dst 'SKILL.md') (Join-Path $broot ("SKILL_{0}_{1}.md.bak" -f $d.Name, $ts))
            Remove-Item $dst -Recurse -Force
        }
        Copy-Item $d.FullName $dst -Recurse -Force
        Write-Output "Skill: $dst"
    }
}

switch ($target) {
    { $_ -in 'claude', 'codex', 'agents' } { $hosts = @($target) }
    'both' { $hosts = @('claude', 'codex') }
    'auto' {
        $c = 0
        if (Test-Path (Join-Path $realHome '.claude')) { $c++ }
        if (Test-Path (Join-Path $realHome '.codex')) { $c++ }
        if ($c -gt 1) { Write-Error '同时检测到 ~/.claude 与 ~/.codex，请用 --target 明确指定。'; exit 1 }
        if ($c -eq 0) { Write-Error '未检测到 ~/.claude 或 ~/.codex，请用 --target 明确指定。'; exit 1 }
        $hosts = if (Test-Path (Join-Path $realHome '.claude')) { @('claude') } else { @('codex') }
    }
    default { Write-Error "未知 --target: $target"; exit 1 }
}

foreach ($h in $hosts) { Copy-Host $h }
Write-Output "完成（兜底模式）。备份在 $broot"
