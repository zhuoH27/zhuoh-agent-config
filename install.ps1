# agent-config 极简入口（Windows PowerShell 5.1+ / pwsh 7 + Python 3.10+）。
# 核心逻辑在 scripts/agent_sync.py 与 scripts/sync_lib/（Python 3 标准库）；本文件以 UTF-8 BOM + CRLF 保存（.gitattributes）。
# 有 Python：透传参数（--verify 映射为 doctor）。
# 无 Python：裸机兜底，纯拷贝规则/skills/prompts 到宿主（默认 abort 保护已有文件；--mode replace 显式覆盖，覆盖前分层备份；不删额外文件）。
# 兼容参数：[--dry-run|--apply|--verify] --target auto|claude|codex|agents|zcode|both
#           --mode append|replace|abort --home 目录 --version
# 安全边界：无网络访问；不执行任意代码；备份统一存 ~/.zhuoh-agent-backup/<TS>/<host>/...。

$VERSION = '3.9.0'
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) } catch {}

if ($args.Count -eq 1 -and $args[0] -eq '--version') {
    Write-Output "agent-config $VERSION (ps1)"
    exit 0
}

$Repo = $PSScriptRoot

# 定位可用 Python 3.8+（过滤 Microsoft Store WindowsApps 占位别名）
$Py = $null
$PyArgs = @()
foreach ($cmdName in @('python', 'python3', 'py')) {
    $candidates = @(Get-Command $cmdName -All -ErrorAction SilentlyContinue)
    foreach ($cand in $candidates) {
        if (-not $cand.Source) { continue }
        if ($cand.Source -match 'WindowsApps\\python3?\.exe$') { continue }
        $tryArgs = if ($cand.Source -match 'py\.exe$') { @('-3') } else { @() }
        try {
            & $cand.Source @tryArgs -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) {
                $Py = $cand
                $PyArgs = $tryArgs
                break
            }
        } catch {}
    }
    if ($Py) { break }
}

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
    & $Py.Source @PyArgs -I $engine $sub @pass
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
        '--apply'      { }
        '--dry-run'    { Write-Error '兜底模式不支持 --dry-run，请安装 Python。'; exit 1 }
        '--verify'     { Write-Error '兜底模式不支持 --verify，请安装 Python。'; exit 1 }
        '--skill-mode' { Write-Error '兜底模式不支持 --skill-mode，请安装 Python。'; exit 1 }
        default        { Write-Error "兜底模式不支持未知参数：$($RawArgs[$i])"; exit 1 }
    }
    $i++
}

$realHome = if ($homeArg) {
    if ($homeArg -eq '~') { $env:USERPROFILE } elseif ($homeArg -match '^~[\\/]') { Join-Path $env:USERPROFILE ($homeArg -replace '^~[\\/]+', '') } else { $homeArg }
} else { $env:USERPROFILE }

$ts = if ($env:AGENT_CONFIG_TS) { $env:AGENT_CONFIG_TS } else { [DateTime]::Now.ToString('yyyyMMdd_HHmmss') }
$broot = Join-Path $realHome ".zhuoh-agent-backup\$ts"
$script:BackupUsed = $false

function Backup-Target([string]$srcFile, [string]$hostKey, [string]$hostRoot) {
    $stem = [IO.Path]::GetFileNameWithoutExtension($srcFile)
    $ext = [IO.Path]::GetExtension($srcFile)
    $dstDir = Join-Path $broot $hostKey
    $fullSrcParent = [IO.Path]::GetFullPath((Split-Path -Parent $srcFile)).TrimEnd('\', '/')
    $fullHostRoot = [IO.Path]::GetFullPath($hostRoot).TrimEnd('\', '/')
    if ($fullSrcParent.StartsWith($fullHostRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        $rel = $fullSrcParent.Substring($fullHostRoot.Length).TrimStart('\', '/')
        if ($rel) { $dstDir = Join-Path $dstDir $rel }
    }
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
    $cand = Join-Path $dstDir ("{0}_{1}{2}.bak" -f $stem, $ts, $ext)
    $n = 2
    while (Test-Path $cand) {
        $cand = Join-Path $dstDir ("{0}_{1}_{2}{3}.bak" -f $stem, $ts, $n, $ext)
        $n++
    }
    Copy-Item $srcFile $cand
    $script:BackupUsed = $true
    return $cand
}

function Test-Link([string]$p) {
    # 5.1/7 对悬空链接的 Get-Item 行为不一：拿不到条目时再看父目录列举，缺失文件返回 False
    $item = Get-Item -Force -LiteralPath $p -ErrorAction SilentlyContinue
    if ($null -ne $item) {
        return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    }
    $parent = Split-Path -Parent $p
    if (-not (Test-Path -LiteralPath $parent)) { return $false }
    $name = Split-Path -Leaf $p
    $entry = Get-ChildItem -Force -LiteralPath $parent -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $name } | Select-Object -First 1
    return ($null -ne $entry)
}

try {
    $manifest = Get-Content (Join-Path $Repo 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Error "manifest.json 解析失败：$_（兜底模式依赖 manifest.json 定位宿主路径）"
    exit 1
}
if (-not $manifest.hosts) { Write-Error 'manifest.json 缺少 hosts，兜底模式无法定位宿主路径'; exit 1 }
if (-not $manifest.sources -or -not $manifest.sources.rules -or -not $manifest.sources.skills) {
    Write-Error 'manifest.json 缺少 sources（rules/skills），兜底模式无法定位源文件'; exit 1
}

function Test-SameFile([string]$a, [string]$b) {
    # 幂等判定：先比大小再比 SHA256，相同则跳过写入与备份
    # 诊断输出：比对失败时把差异打到日志，便于 CI 排查
    try {
        $fa = Get-Item -LiteralPath $a; $fb = Get-Item -LiteralPath $b
        if ($fa.Length -ne $fb.Length) {
            Write-Host "[diag] Test-SameFile size differs: $a($($fa.Length)) vs $b($($fb.Length))"
            return $false
        }
        $ba = [System.IO.File]::ReadAllBytes($fa.FullName)
        $bb = [System.IO.File]::ReadAllBytes($fb.FullName)
        if ([Convert]::ToBase64String($ba) -ne [Convert]::ToBase64String($bb)) { Write-Host "[diag] Test-SameFile content differs: $a($($fa.Length)) vs $b($($fb.Length))" ; return $false }
        return $true
    } catch {
        Write-Host "[diag] Test-SameFile error: $($_.Exception.Message)"
        return $false
    }
}

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
    if (Test-Link $rules) { Write-Error "$rules 是链接（符号链接/junction/悬空链接），拒绝写入（人工处理）"; exit 1 }
    $rulesSrc = Join-Path $Repo ([string]$manifest.sources.rules)
    if (Test-Path $rules) {
        if (Test-SameFile $rulesSrc $rules) {
            Write-Output "已最新: $rules"
        } else {
            if ($mode -eq 'abort') { Write-Error "$rules 已存在；兜底默认 --mode abort 停止（人工合并后重跑，或显式 --mode replace，覆盖前自动备份）"; exit 1 }
            $bak = Backup-Target $rules $key $root
            Write-Output "备份: $rules -> $bak"
            Copy-Item $rulesSrc $rules -Force
            Write-Output "写入: $rules"
        }
    } else {
        New-Item -ItemType Directory -Path $root -Force | Out-Null
        Copy-Item $rulesSrc $rules -Force
        Write-Output "写入: $rules"
    }
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    if (Test-Link $skillsDst) {
        Write-Output "跳过 skills（$skillsDst 是链接，人工处理）"
    } else {
        New-Item -ItemType Directory -Path $skillsDst -Force | Out-Null
        foreach ($d in Get-ChildItem (Join-Path $Repo ([string]$manifest.sources.skills)) -Directory) {
            $dst = Join-Path $skillsDst $d.Name
            if (Test-Link $dst) { Write-Output "跳过 Skill $($d.Name)（$dst 是链接，人工处理）"; continue }
            New-Item -ItemType Directory -Path $dst -Force | Out-Null
            foreach ($f in Get-ChildItem $d.FullName -File -Recurse) {
                $rel = $f.FullName.Substring($d.FullName.Length).TrimStart('\', '/')
                $tgtFile = Join-Path $dst $rel
                $relParts = $rel -split '[\\/]'
                $blocked = $false
                $walk = $dst
                for ($j = 0; $j -lt $relParts.Count - 1; $j++) {
                    $walk = Join-Path $walk $relParts[$j]
                    if (Test-Link $walk) { Write-Output "跳过 $tgtFile（中间目录 $walk 是链接，人工处理）"; $blocked = $true; break }
                }
                if ($blocked) { continue }
                if (Test-Link $tgtFile) { Write-Output "跳过 $tgtFile（目标是链接，人工处理）"; continue }
                $tgtParent = Split-Path $tgtFile -Parent
                if (-not (Test-Path $tgtParent)) { New-Item -ItemType Directory -Path $tgtParent -Force | Out-Null }
                if (Test-Path $tgtFile) {
                    if (Test-SameFile $f.FullName $tgtFile) { continue }
                    $null = Backup-Target $tgtFile $key $root
                }
                Copy-Item $f.FullName $tgtFile -Force
            }
            Write-Output "Skill: $dst"
        }
    }
    if ($h.prompts_dir) {
        $pSrc = Join-Path $Repo ([string]$manifest.sources.prompts)
        if (Test-Path $pSrc) {
            $pdir = Join-Path $root ([string]$h.prompts_dir)
            if (Test-Link $pdir) {
                Write-Output "跳过 prompts（$pdir 是链接，人工处理）"
            } else {
                New-Item -ItemType Directory -Path $pdir -Force | Out-Null
                foreach ($f in Get-ChildItem $pSrc -Filter '*.md' -File) {
                    $tgtFile = Join-Path $pdir $f.Name
                    if (Test-Link $tgtFile) { Write-Output "跳过 $tgtFile（目标是链接，人工处理）"; continue }
                    if (Test-Path $tgtFile) {
                        if (Test-SameFile $f.FullName $tgtFile) { continue }
                        $null = Backup-Target $tgtFile $key $root
                    }
                    Copy-Item $f.FullName $tgtFile -Force
                }
                Write-Output "Prompt: $pdir"
            }
        }
    }
}

switch ($target) {
    { $_ -in 'claude', 'codex', 'agents', 'zcode' } { $hosts = @($target) }
    'both' { $hosts = @('claude', 'codex') }
    'auto' {
        if ($env:CLAUDECODE -or $env:CLAUDE_CODE_ENTRYPOINT) {
            $hosts = @('claude')
        } elseif ($env:CODEX_THREAD_ID) {
            $hosts = @('codex')
        } else {
            $found = @()
            foreach ($h in @('claude', 'codex', 'agents', 'zcode')) {
                if (Test-Path (Join-Path $realHome ('.' + $h))) { $found += $h }
            }
            if ($found.Count -gt 1) { Write-Error ('检测到多个宿主（{0}），请用 --target 明确指定。' -f ($found -join '、')); exit 1 }
            if ($found.Count -eq 0) { Write-Error '未检测到 ~/.claude、~/.codex、~/.agents 或 ~/.zcode，请用 --target 明确指定。'; exit 1 }
            $hosts = $found
        }
    }
    default { Write-Error "未知 --target: $target"; exit 1 }
}

foreach ($h in $hosts) { Copy-Host $h }
if ($script:BackupUsed) {
    Write-Output "完成（兜底模式）。备份在 $broot"
} else {
    Write-Output '完成（兜底模式）。本次无覆盖文件，未生成备份。'
}
