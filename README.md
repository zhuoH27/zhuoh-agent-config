# zhuoh-agent-config
把一套全局规则和 4 个纯文档 Skill 变成可维护、可一键安装的配置仓库。

- 适用宿主：Claude Code（`~/.claude`）、Codex CLI（`~/.codex`），也支持 `~/.agents` 约定。
- **零运行时依赖**：macOS/Linux 用系统自带的 `sh`，Windows 用系统自带的 Windows PowerShell 5.1+，无需安装 Python 或任何其他程序。
- 安装产物只有 Markdown：规则文件 + 4 个 `SKILL.md`。安装器（`install.sh` / `install.ps1`）只在本仓库里运行，不会落进配置目录。
- 自带备份、受管区块、dry-run 与校验；不删除旧 Skill，不自动改 `.gitignore`。

## 给 AI 的一键指令
把下面整段发给新 agent（fork 本仓库的人请把 URL 换成自己的仓库地址）：

```text
请阅读并执行 https://github.com/zhuoH27/zhuoh-agent-config 的 BOOTSTRAP.md。
要求：
1. 先克隆仓库到本地临时目录，不要直接改我的现有配置。
2. 运行安装器 dry-run（macOS/Linux：sh install.sh --dry-run --target auto；Windows：powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --dry-run --target auto），把将创建/覆盖的文件、备份清单和规则文件处理方式给我确认。
3. 我明确批准后，再运行同款 --apply --target <claude|codex|both>。
4. 最后运行同款 --verify --target <...>，把结果贴给我。
5. 遇到需要我决策的地方停下；被权限或沙箱拒绝时停止汇报，不要换工具或路径绕过；不要删除旧 Skill 或 _backup。
```

懒人版：

```text
读取 https://raw.githubusercontent.com/zhuoH27/zhuoh-agent-config/main/BOOTSTRAP.md 并按其执行，先 dry-run 等我批准。
```

## 事实来源
`AGENTS.md` 与 `skills/*/SKILL.md` 是唯一事实来源（历史上由一次性配置指令逐字提取，原始存档已移除）。修改请直接改这些源文件，保持 UTF-8（无 BOM）、LF 换行。铁律编号（1–10）不得重排：Skill 按编号引用铁律（如 zhuoh-paper-writing 引用第 3 条），`--verify` 也会校验编号。

## 仓库结构
```text
zhuoh-agent-config/
├── AGENTS.md                     # 全局铁律（带 BEGIN/END 受管标记）
├── BOOTSTRAP.md                  # 给执行 agent 的安装说明
├── README.md                     # 本文件
├── install.sh                    # 安装器（POSIX sh，macOS/Linux）
├── install.ps1                   # 安装器（Windows PowerShell 5.1+，UTF-8 BOM + CRLF 保存）
├── LICENSE                       # MIT
├── .gitignore / .gitattributes   # 忽略备份与缓存；*.sh 强制 LF，*.ps1 强制 CRLF
├── .github/workflows/ci.yml      # Ubuntu（sh）+ Windows（ps1）自动测试
├── tests/
│   ├── test_install.py           # 两个安装器的黑盒测试（双驱动）
│   ├── test_content.py           # 仓库内容一致性校验（铁律引用、标注词汇、版本一致）
│   └── test_pptx_font.py         # zhuoh-ppt-maker 字体片段的开发期实测（需 python-pptx，缺失则跳过）
├── skills/
│   ├── zhuoh-code-standards/SKILL.md
│   ├── zhuoh-ppt-maker/SKILL.md
│   ├── zhuoh-paper-writing/SKILL.md
│   └── zhuoh-idea-evaluation/SKILL.md
└── prompts/
    └── sync.md                   # 已装宿主的后续同步指令
```

## 安装
macOS / Linux（含任意提供 POSIX sh 的环境，如 Git Bash）：
```bash
sh install.sh --dry-run --target auto
sh install.sh --apply --target claude    # 或 codex / both / agents
sh install.sh --verify --target claude
```
Windows（Windows PowerShell 5.1 及以上，或 pwsh 7）：
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --dry-run --target auto
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --apply --target claude
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --verify --target claude
```
`-ExecutionPolicy Bypass` 只作用于本次进程，不改系统策略。

安装器会被执行。运行前请（或要求执行 agent 先）审阅：两个脚本都无网络访问、无 `eval`/子进程（ps1）/不执行任意代码（sh 侧仅调用列在脚本头部的常规文本工具），只读写宿主规则文件、`skills/*/SKILL.md` 与 `_backup/`；写入走临时文件+原子改名。需要可复现时，用 tag 或 commit 的 URL 固定版本。

**符号链接限制**：规则文件或 Skill 文件本身是符号链接时，安装器拒绝写入并停止；宿主根目录为符号链接时会按其指向的路径操作。dotfiles/stow 用户请先确认链接结构。

## 规则文件已有内容怎么办
- **没有受管标记**：默认 `--mode append`，把铁律区块追加到文件末尾，保留原有内容（含末尾空行），并先备份。只有明确需要整文件替换时才用 `--mode replace`；`--mode abort` 会直接停止。
- **疑似旧版铁律**：dry-run 会输出 `[警告]`——文件里像是有未受管标记的旧版铁律，直接追加会重复或冲突，请人工合并，或经用户确认后改用 `--mode replace`。
- **已有一对标记**：只替换 `BEGIN` 到 `END` 之间的区块，不碰其余内容；dry-run 会附上区块差异摘要。
- **标记异常**（只有一半、多对、顺序颠倒）：停止，不自动修，先人工确认。
- **编码与格式**：非 UTF-8 的规则文件（如 GBK/UTF-16）会以可读错误停止，请先转成 UTF-8。已有文件的换行风格（LF/CRLF）沿用原文件；写入一律 UTF-8 无 BOM，文件带 BOM 时任何写入都会顺带剥离（先备份）；区块已最新但文件带 BOM 时，apply 会原样重写一次仅剥 BOM。

## 更新
1. 改本仓库里的 `AGENTS.md` 或 `skills/*/SKILL.md`，commit 后 push。
2. 新 agent 继续用同一个仓库地址，拿到的就是最新版。
3. 已安装的 agent 发 `prompts/sync.md` 里的指令，让它重新克隆最新版后 dry-run、apply、verify。
需要固定版本时，用 tag 或 commit 的 URL，而不是 `main` 分支。

## 安全边界
- 写入前按系统时间戳备份到宿主根目录的 `_backup/`，不覆盖旧备份；备份重名在时间戳后加 `_2`、`_3`（与铁律第 2 条的格式一致）。
- 同名 Skill 只覆盖 `SKILL.md`，目录内其他文件不动。
- 功能重叠的旧 Skill 只记录、提醒，不删除。
- 已有文件的换行风格（LF/CRLF）沿用原文件，不整体改写。
- 不写密钥、令牌或个人信息；本仓库本身不含密钥。
- 私有仓库需要登录或 token，无法只靠 URL 一键；建议公开。

## 作者偏好声明
`zhuoh-ppt-maker` 的默认交付形态（未明说 .pptx 时默认离线网页并提示可复刻）、文献汇报署名占位（「用户」「导师」）、字体搭配（微软雅黑 + Times New Roman）、正文黑白配色，以及 `zhuoh-paper-writing` 默认参考文献版本策略，都是**作者个人偏好**。fork 本仓库请自行修改 `skills/*/SKILL.md`；这些选择不构成对其他方案的否定。

## 开发与测试
```bash
python -m pip install pytest
python -m pytest tests/ -q
```
Python 只在开发与 CI 侧使用（驱动黑盒测试），用户安装机器零依赖。测试全部通过 `--home` 指向临时目录运行（含带空格的路径），不会触碰真实配置。CI（`.github/workflows/ci.yml`）在 Ubuntu（驱动 `install.sh`）与 Windows（驱动 `install.ps1`，兼测 Git Bash 的 `install.sh`）上自动跑同一套测试。
另注意：在本仓库内开发时，Codex 会把仓库根的 `AGENTS.md` 当作项目指令，与全局安装版同时生效（推理，未实测）。

## 版本
当前版本见 `install.sh` / `install.ps1` 头部的 `VERSION` 常量。发布固定版本：
```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```
tag 与 push 必须使用同一个版本号。

## 许可
MIT，见 `LICENSE`。

## 常见问题
- **`--target auto` 报两个宿主同时存在**：用 `--target claude`、`--target codex` 或 `--target both` 明确指定，别让它猜。环境变量已唯一指向宿主（Claude：`CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT`；Codex：`CODEX_THREAD_ID`）时优先按环境变量判定。
- **写入 `~/.claude` 被权限拒绝**：停止，由用户自己在终端运行安装器，把输出贴回会话。
- **报“无法按 UTF-8 解码”**：目标文件是 GBK/UTF-16 等编码，先转成 UTF-8 再运行。
- **新会话看不到 Skill**：确认 `SKILL.md` 第一行是 `---`、`name` 与目录名一致、`description` 是单行；然后重启宿主会话。
- **想回滚**：从对应 `_backup/` 目录取回备份文件，按原路径放回。
