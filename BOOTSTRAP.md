# BOOTSTRAP：给执行 Agent 的安装说明

你是被派来把本仓库配置安装到用户宿主的 agent。严格按下面执行，不要即兴发挥。

## 0. 读取顺序与代码审阅
1. `README.md`
2. `BOOTSTRAP.md`
3. `install.py`（先审阅，见下）
4. `AGENTS.md`
5. `skills/*/SKILL.md`

先审阅 `install.py`：确认它只使用标准库、无网络访问（`socket`/`urllib`/`requests`）、无子进程（`subprocess`/`os.system`）、无 `eval`/`exec`；它只应读写宿主规则文件、`skills/*/SKILL.md` 与 `_backup/`。发现任何超出此范围的行为，停下汇报，不得执行。

## 1. 克隆到临时目录并记录版本
```bash
cd "$(mktemp -d)"   # PowerShell: cd (New-Item -ItemType Directory -Path (Join-Path $env:TEMP ("ac" + [guid]::NewGuid().ToString("N").Substring(0,8))))
git clone https://github.com/zhuoH27/zhuoh-agent-config.git agent-config
cd agent-config
git rev-parse HEAD   # 记下 commit hash，汇报时附上
```
不能 clone 时，下载 ZIP 并解压，进入含 `install.py` 的目录。不要把仓库放进 `~/.claude` 或 `~/.codex` 里面。

## 2. 识别宿主
```bash
python install.py --dry-run --target auto
```
- 若输出“同时检测到 ~/.claude 与 ~/.codex”，停下来问用户选 `claude`、`codex` 还是 `both`。不要替用户选。
- 若环境变量已唯一指向宿主，按输出继续。
- Python 不可用时改用 `py install.py ...`，不要跳过 dry-run。

## 3. 展示计划
把 dry-run 输出原样给用户（含区块 diff，如有），说明：
- 将新建或替换哪个规则文件；
- 规则文件是追加还是整文件替换；
- 将新建或覆盖哪些 Skill；
- 会产生哪些备份。

明确问：“是否批准 apply（target = X）？”——写出具体 target，不要含糊。

dry-run 输出中出现 `[警告]` 时必须停下，逐条向用户说明，由用户决定处理方式（人工合并、`--mode replace` 或放弃），不得自行选择 `--mode`。

## 4. 执行
```bash
python install.py --apply --target <已确认的 target>
```
- 用户未批准，不执行。
- 权限或沙箱拒绝时停止并汇报，不要换工具、换路径或放宽沙箱参数。
- 不要修改 `_backup/` 里的任何历史备份。

## 5. 校验
```bash
python install.py --verify --target <target>
```
把结果表贴给用户。任何一项 FAIL 都停下，不要声称成功。

## 6. 汇报与收尾
汇报：宿主、写入路径、备份路径、校验结果、安装的 commit hash、未验证项。
提醒用户：新开一个宿主会话，让它列出可用 Skill，确认 4 个都在。同一个会话里新写的 Skill 不保证被重新扫描。

## 边界
- 不删除旧 Skill；发现功能重叠只记录并提醒。
- 不写密钥、令牌或个人信息。
- 不自动修改 `.gitignore`。
- 只有用户明确要求时才用 `--mode replace`；默认追加。
