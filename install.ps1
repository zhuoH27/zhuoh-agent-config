# agent-config 极简入口（Windows PowerShell 5.1+ / pwsh 7）。
# 核心逻辑在 scripts/agent_sync.py（Python 3 标准库）；本文件以 UTF-8 BOM + CRLF 保存（.gitattributes）。
# 有 Python：透传参数（--verify 映射为 doctor）。
# 无 Python：裸机兜底，纯拷贝规则/skills/prompts 到宿主（默认 abort 保护已有文件；--mode replace 显式覆盖，覆盖前备份；不删额外文件）。
# 兼容原 v2.2.0 参数：[--dry-run|--apply|--verify] --target auto|claude|codex|agents|both
#                     --mode append|replace|abort --home 目录 --version
# 安全边界：无网络访问；不执行任意代码；备份统一存 ~/.zhuoh-agent-backup/<TS>/。

$VERSION = '3.2.0'
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
Write-Output '未检测到 Python，使用裸机兜底模式（纯拷贝整文件覆盖，功能受限）。'

$RawArgs = $args
$target = 'auto'
$homeArg = $null
    $mode = 'abort'
$i = 0
while ($i -lt $RawArgs.Count) {
    switch ($RawArgs[$i]) {
        '--target' {
            if ($i + 1 -ge $RawArgs.Count) { Write-Error '--target 缺少参数值'; exit 1 }
            $i++; $target = [string]$RawArgs[$i]
        }
        '--home' {
            if ($i + 1 -ge $RawArgs.Count) { Write-Error '--home 缺少参数值'; exit 1 }
            $i++; $homeArg = [string]$RawArgs[$i]
        }
        '--mode' {
            if ($i + 1 -ge $RawArgs.Count) { Write-Error '--mode 缺少参数值'; exit 1 }
            $i++; $mode = [string]$RawArgs[$i]
            if ($mode -notin @('replace', 'abort')) {
                Write-Error "兜底模式不支持 --mode $mode（仅支持 replace 或 abort），请安装 Python。"
                exit 1
            }
        }
        '--dry-run' { Write-Error '兜底模式不支持 --dry-run，请安装 Python。'; exit 1 }
        '--verify'  { Write-Error '兜底模式不支持 --verify，请安装 Python。'; exit 1 }
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

function Backup-Target([string]$srcFile) {
    $stem = [IO.Path]::GetFileNameWithoutExtension($srcFile)
    $ext = [IO.Path]::GetExtension($srcFile)
    $cand = Join-Path $broot ("{0}_{1}{2}.bak" -f $stem, $ts, $ext)
    $n = 2
    while (Test-Path $cand) {
        $cand = Join-Path $broot ("{0}_{1}_{2}{3}.bak" -f $stem, $ts, $n, $ext)
        $n++
    }
    Copy-Item $srcFile $cand
    return $cand
}

try {
    $manifest = Get-Content (Join-Path $Repo 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Error "manifest.json 解析失败：$_（兜底模式依赖 manifest.json 定位宿主路径）"
    exit 1
}
if (-not $manifest.hosts) { Write-Error 'manifest.json 缺少 hosts，兜底模式无法定位宿主路径'; exit 1 }

function Copy-Host([string]$key) {
    $h = $manifest.hosts.$key
    if (-not $h -or -not $h.root -or -not $h.rules_target -or -not $h.skills_dir) {
        Write-Error "manifest hosts.$key 缺少必需字段（root/rules_target/skills_dir）"
        exit 1
    }
    $hr = [string]$h.root
    if ($hr -eq '~') { $root = $realHome }
    elseif ($hr.StartsWith('~')) { $root = Join-Path $realHome ($hr -replace '^~[\\/]+', '') }
    elseif ([IO.Path]::IsPathRooted($hr)) { $root = $hr }
    else { Write-Error "manifest root 必须以 ~ 开头或为绝对路径: $hr"; exit 1 }
    $rules = Join-Path $root ([string]$h.rules_target)
    $skillsDst = Join-Path $root ([string]$h.skills_dir)
    New-Item -ItemType Directory -Path $skillsDst -Force | Out-Null
    if (Test-Path $rules) {
        if ($mode -eq 'abort') { Write-Error "$rules 已存在；兜底默认 --mode abort 停止（人工合并后重跑，或显式 --mode replace，覆盖前自动备份）"; exit 1 }
        $bak = Backup-Target $rules
        Write-Output "备份: $rules -> $bak"
    }
    Copy-Item (Join-Path $Repo ([string]$manifest.sources.rules)) $rules -Force
    Write-Output "写入: $rules"
    foreach ($d in Get-ChildItem (Join-Path $Repo ([string]$manifest.sources.skills)) -Directory) {
        $dst = Join-Path $skillsDst $d.Name
        New-Item -ItemType Directory -Path $dst -Force | Out-Null
        foreach ($f in Get-ChildItem $d.FullName -File -Recurse) {
            $rel = $f.FullName.Substring($d.FullName.Length).TrimStart('\', '/')
            $tgtFile = Join-Path $dst $rel
            $tgtParent = Split-Path $tgtFile -Parent
            if (-not (Test-Path $tgtParent)) { New-Item -ItemType Directory -Path $tgtParent -Force | Out-Null }
            if (Test-Path $tgtFile) { $null = Backup-Target $tgtFile }
            Copy-Item $f.FullName $tgtFile -Force
        }
        Write-Output "Skill: $dst"
    }
    if ($h.prompts_dir) {
        $pSrc = Join-Path $Repo ([string]$manifest.sources.prompts)
        if (Test-Path $pSrc) {
            $pdir = Join-Path $root ([string]$h.prompts_dir)
            New-Item -ItemType Directory -Path $pdir -Force | Out-Null
            foreach ($f in Get-ChildItem $pSrc -Filter '*.md' -File) {
                $tgtFile = Join-Path $pdir $f.Name
                if (Test-Path $tgtFile) { $null = Backup-Target $tgtFile }
                Copy-Item $f.FullName $tgtFile -Force
            }
            Write-Output "Prompt: $pdir"
        }
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
