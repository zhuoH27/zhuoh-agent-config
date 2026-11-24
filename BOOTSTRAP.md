# BOOTSTRAP：新机首次部署引导

你是被派来把本仓库配置安装到用户宿主的 agent。严格按下面执行，不要即兴发挥。本仓库仅维护 Windows（PowerShell 5.1+ / pwsh 7 + Python 3）；日常维护（已装过本仓库）不走本文件，直接按 `skills/zhuoh-config-sync/SKILL.md` 的闭环执行。

## 0. 读取顺序与代码审阅
1. `README.md`
2. `BOOTSTRAP.md`（本文件）
3. `scripts/agent_sync.py`（先审阅，见下）
4. `AGENTS.md`
5. `skills/*/SKILL.md`

先审阅引擎与入口 `install.ps1`：确认它们无网络访问、无 `eval`、不执行任意代码；只读写宿主规则文件、`skills/*/SKILL.md`、`~/.codex/prompts/` 与 `~/.zhuoh-agent-backup/`。发现任何超出此范围的行为，停下汇报，不得执行。

## 1. 克隆仓库并记录版本
```powershell
$tmp = Join-Path $env:TEMP ("ac" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Path $tmp | Out-Null
Set-Location $tmp
git clone https://github.com/zhuoH27/zhuoh-agent-config.git agent-config
Set-Location agent-config
git rev-parse HEAD   # 记下 commit hash，汇报时附上
```
不能 clone 时，下载 ZIP 并解压，进入含 `scripts/agent_sync.py` 的目录。不要把仓库放进 `~/.claude` 或 `~/.codex` 里面。

## 2. 检查 Python 并识别宿主
需要 Windows 与 Python 3（标准库即可）。无 Python 的机器走兜底路径（见第 4 节）。
```bash
python scripts/agent_sync.py setup --dry-run --target auto
```
- 输出“同时检测到 ~/.claude 与 ~/.codex”时，停下问用户选 `claude`、`codex` 还是 `both`，不要替用户选。
- 环境变量已唯一指向宿主时按输出继续。
- 不要跳过 dry-run。

## 3. 展示计划
把 dry-run 输出原样给用户，说明：将新建/替换/追加哪个规则文件、将新建或覆盖哪些技能、会产生哪些备份（位于 `~/.zhuoh-agent-backup/<时间戳>/`）。
明确问：“是否批准 apply（target = X）？”——写出具体 target。
dry-run 出现 `[警告]`（疑似旧版未受管铁律、标记异常）时必须停下，逐条向用户说明，由用户决定处理方式（人工合并、`--mode replace` 或放弃），不得自行选择 `--mode`。

## 4. 执行
```bash
python scripts/agent_sync.py setup --target <已确认的 target>
```
无 Python 的 Windows：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --target <target>`——入口会自动落到纯拷贝兜底（默认 `--mode abort` 保护已有规则文件；显式 `--mode replace` 才覆盖，覆盖前备份）。
- 用户未批准，不执行。
- 权限或沙箱拒绝时停止并汇报，不要换工具、换路径或放宽沙箱参数。
- 不修改 `~/.zhuoh-agent-backup/` 里的任何历史备份。

## 5. 校验
```bash
python scripts/agent_sync.py doctor --target <target>
```
把结果贴给用户。任何 `[警告]` 都停下，不要声称成功。

## 6. 汇报与收尾
汇报：宿主、写入路径、备份路径、校验结果、安装的 commit hash、未验证项。
提醒用户新开宿主会话，让它列出可用 Skill，确认全部技能都在（同一会话里新装的 Skill 不保证被重新扫描）。

## 边界
- 不删除宿主里的第三方技能；发现功能重叠只记录并提醒。
- 不写密钥、令牌或个人信息。
- 不自动修改 `.gitignore`。
- 只有用户明确要求时才用 `--mode replace`；默认追加。
