# zhuoh-agent-config
把一套全局规则和 6 个纯文档 Skill 变成可维护、可一键安装的配置仓库。

- 适用宿主：Claude Code（`~/.claude`）、Codex CLI（`~/.codex`）、`~/.agents` 约定。
- **平台：仅 Windows**（PowerShell 5.1+ / pwsh 7 + Python 3）；macOS/Linux 的 sh 入口与对应 CI 已移除，不再维护。
- **核心是 Python 引擎**：`scripts/agent_sync.py` + `scripts/sync_lib/`（仅 Python 3 标准库）提供 setup / doctor / audit / status 四个子命令；`install.ps1` 是唯一薄入口（无 Python 时退化为纯拷贝兜底）。
- 安装产物只有 Markdown：规则文件 + 6 个 `SKILL.md`（含 `references/` 与 `zhuoh-config-sync` 自维护技能）。
- 自带分层备份、受管区块、dry-run 与校验；支持每次更新时安全覆盖安装；不删除旧 Skill 与用户额外文件，不自动改 `.gitignore`。

## 给 AI 的一键指令
把下面整段发给新 agent（fork 本仓库的人请把 URL 换成自己的仓库地址）。信任模型提示：一键指令会直接执行线上内容；需要可复现时把 URL 换成 tag 或 commit 的固定版本地址，而不是 `main` 分支：

```text
请阅读并执行 https://github.com/zhuoH27/zhuoh-agent-config 的 BOOTSTRAP.md。
要求：
1. 先克隆仓库到本地临时目录，不要直接改我的现有配置。
2. 运行 python scripts/agent_sync.py setup --dry-run --target auto，把将创建/覆盖的文件、备份清单和规则文件处理方式给我确认。
3. 我明确批准后，再运行同款 setup（去掉 --dry-run）--target <claude|codex|agents|both>。
4. 最后运行 python scripts/agent_sync.py doctor --target <...>，把结果贴给我。
5. 遇到需要我决策的地方停下；被权限或沙箱拒绝时停止汇报，不要换工具或路径绕过；不要删除旧 Skill 或 ~/.zhuoh-agent-backup 里的备份。
```

懒人版：

```text
读取 https://raw.githubusercontent.com/zhuoH27/zhuoh-agent-config/main/BOOTSTRAP.md 并按其执行，先 dry-run 等我批准。
```
同样适用上面的信任模型提示：需要可复现时把 URL 换成 tag 或 commit 的固定版本地址，而不是 `main`。

## 事实来源
`AGENTS.md` 与 `skills/*/SKILL.md` 是唯一事实来源（历史上由一次性配置指令逐字提取，原始存档已移除）。修改请直接改这些源文件，保持 UTF-8（无 BOM）。铁律编号（1–10）不得重排：Skill 按编号引用铁律（如 zhuoh-paper-writing 引用第 3 条），`doctor` 也会校验编号。

## 仓库结构
```text
zhuoh-agent-config/
├── AGENTS.md                     # 全局铁律（带 BEGIN/END 受管标记）
├── BOOTSTRAP.md                  # 新机首次部署引导（给执行 agent）
├── README.md                     # 本文件
├── manifest.json                 # 宿主路径映射清单（声明式单一数据源）
├── install.ps1                   # 唯一薄入口（PowerShell 5.1+；无 Python 时纯拷贝兜底）
├── scripts/
│   ├── agent_sync.py             # CLI 入口（兼容 python -I 隔离模式）
│   └── sync_lib/                 # 核心同步引擎（core / sync / audit，仅 Python 标准库）
├── LICENSE                       # MIT
├── .gitignore / .gitattributes   # 忽略备份与缓存；统一 LF（ps1 例外 CRLF）
├── .github/workflows/ci.yml      # Windows 自动测试与 audit 门禁
├── tests/
│   ├── test_sync_engine.py       # 引擎黑盒测试（--home/--repo 沙盒）
│   ├── test_sync_edge_cases.py   # 引擎安全与边界回归测试
│   ├── test_install_ps1.py       # install.ps1 兜底路径与字节契约测试
│   ├── test_content.py           # 内容一致性校验（动态遍历 skills/* 与 scripts/**）
│   └── test_pptx_font.py         # zhuoh-ppt-maker 字体片段实测（缺 python-pptx 则跳过）
├── skills/                       # 6 个技能
│   ├── zhuoh-code-standards/
│   ├── zhuoh-config-sync/        # Agent 自维护与同步闭环 SOP
│   ├── zhuoh-idea-evaluation/
│   ├── zhuoh-paper-review/
│   ├── zhuoh-paper-writing/
│   └── zhuoh-ppt-maker/
└── prompts/sync.md               # 已装宿主的同步指令
```

## 安装与命令速查
有 Python 3 的 Windows（推荐，全功能）：
```powershell
python scripts/agent_sync.py setup --dry-run --target auto
python scripts/agent_sync.py setup --target claude    # 或 codex / both / agents
python scripts/agent_sync.py doctor --target claude
```
无 Python 的 Windows（兜底，纯拷贝）：
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --target claude
```
`-ExecutionPolicy Bypass` 只作用于本次进程，不改系统策略。兜底模式不支持 `--dry-run`、`--verify` 与受管区块合并（规则文件整文件拷贝；默认 `--mode abort` 保护已有文件，显式 `--mode replace` 才覆盖且覆盖前备份），装好后建议补装 Python 并重跑 setup 获得完整保护。

参数：`--target auto|claude|codex|agents|both`（auto 按环境变量 CLAUDECODE/CLAUDE_CODE_ENTRYPOINT/CODEX_THREAD_ID 优先，其次目录探测，多宿主并存报错；both = claude + codex）；`--mode append|replace|abort`（规则文件合并方式，默认 append；无 Python 兜底默认 abort，仅支持 replace/abort）；`--skill-mode copy|link`（Skill 安装方式，默认读取 `manifest.json`）；`--home 目录`（测试沙盒用）；`AGENT_CONFIG_TS` 环境变量固定备份时间戳（测试用）。

## 规则文件已有内容怎么办
- **没有受管标记**：默认追加铁律区块到文件末尾，保留原有内容（含末尾空行），先备份。需要整文件替换时用 `--mode replace`；`--mode abort` 直接停止。
- **疑似旧版铁律**（含“全局核心铁律”或“不可逆操作确认”字样）：dry-run 输出 `[警告]`，请人工合并或确认后用 `--mode replace`。
- **已有一对标记**：只替换 BEGIN 到 END 之间的区块，不碰其余内容。
- **标记异常**（数量不对、不独占一行或 END 在 BEGIN 之前）：停止，不自动修，先人工确认。
- **编码与格式**：非 UTF-8 规则文件报错停止；换行风格沿用原文件；写入 UTF-8 无 BOM，BOM 会在写入时剥离（先备份）。

## 日常维护（一句话）
对本仓库的 agent 说 **“同步配置”**（或 `/sync`），它会按 `skills/zhuoh-config-sync/SKILL.md` 执行闭环：doctor 体检 → audit 安全门禁 → pytest → 变更摘要 → 你确认后 commit，**push 前必须获你批准**。

## 更新
1. 改本仓库里的 `AGENTS.md` 或 `skills/*`，确认后 commit 并 push。
2. 新 agent 继续用同一个仓库地址，拿到的就是最新版。
3. 已安装的 agent 发 `prompts/sync.md` 里的指令，让它重新克隆最新版后 dry-run、apply、doctor（同名技能与 `references/` 均会备份后覆盖更新）。
需要固定版本时，用 tag 或 commit 的 URL，而不是 `main` 分支。

## 安全边界
- 写入前按系统时间戳分层备份到 `~/.zhuoh-agent-backup/<TS>/<host>/<相对目录>/<原名>_<TS>.<ext>.bak`（重名加 `_2`/`_3`）；不覆盖旧备份；技能目录内零 `.bak` 残留。
- 同名 Skill 仅备份并覆盖仓库包含的文件（`SKILL.md` 与 `references/`），目录内其他文件不动；功能重叠的旧 Skill 只提醒，不删除。
- 已有文件的换行风格沿用原文件；不整体改写。
- 不写密钥、令牌或个人信息；本仓库本身不含密钥；`audit` 命令在推送前扫描密钥与硬编码本地路径。
- 私有仓库需要登录或 token，无法只靠 URL 一键；建议公开。
- `manifest.json` 的宿主 `root` 须以 `~` 开头或为绝对路径；兜底模式对相对 root 直接报错不写入。
- **链接（符号链接/junction）**：引擎侧——规则文件是指向仓库源的链接时判“链接健康”跳过，其他符号链接（含悬空）拒绝写入并报错；技能目录是符号链接时跳过该技能（junction 目录会照常写入，穿透到链接位置）；技能文件是链接时仅当内容有差异才备份后原子替换（替换链接本身，不穿透），内容相同不动，悬空链接按“新增”直接替换。兜底侧更保守——规则文件是任何链接（含 junction/悬空）一律拒绝写入退出；skills 根、技能目录、技能内中间目录、技能与提示词文件、prompts 根是任何链接（含 junction/悬空）一律跳过并提示人工处理。宿主根目录（如 `~/.claude`）本身是链接时两边都会跟随写入。
- **安装器备份与铁律第 2 条**：命名格式与相对路径保留原则一致，但安装器统一备份到 `~/.zhuoh-agent-backup/<TS>/<host>/...`，不用项目内 `_backup/`（后者约束 agent 修改既有文件时的备份行为；安装器写入是计划内批量操作，走统一备份根）。

## 作者偏好声明
`zhuoh-ppt-maker` 的默认交付形态、文献汇报署名占位、学术答辩默认双字体与黑白红预设，`zhuoh-paper-writing` 默认参考文献版本策略，`zhuoh-paper-review` 的 IMRaD 默认范式、优先级权重与 ✅/⚠️/❌ 输出格式，以及 `zhuoh-config-sync` 的“复制优先于链接”默认模式，都是**作者个人偏好**。fork 本仓库请自行修改 `skills/*/SKILL.md` 与 `manifest.json`；这些选择不构成对其他方案的否定。

## 开发与测试
```bash
python -m pip install pytest
python -m pytest tests/ -q
```
测试全部通过 `--home` / `--repo` 指向临时目录运行（含带空格的路径），不触碰真实配置。CI（`.github/workflows/ci.yml`）在 Windows 上跑同一套测试并执行 `audit` 门禁。

## 版本
当前版本见 `scripts/sync_lib/core.py` 头部的 `VERSION` 常量（与 `install.ps1` 保持同步）。发布固定版本：
```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```
tag 与 push 必须使用同一个版本号。

## 许可
MIT，见 `LICENSE`。

## 常见问题
- **`--target auto` 报“检测到多个宿主”**：按报错列出的宿主用 `--target claude`、`--target codex`、`--target agents` 或 `--target both` 明确指定。环境变量已唯一指向宿主时优先按环境变量判定。
- **写入 `~/.claude` 被权限拒绝**：停止，由用户自己在终端运行安装器，把输出贴回会话。
- **报“无法按 UTF-8 解码”**：目标文件是 GBK/UTF-16 等编码，先转成 UTF-8 再运行。
- **新会话看不到 Skill**：确认 `SKILL.md` 第一行是 `---`、`name` 与目录名一致、`description` 是单行；然后重启宿主会话。
- **想回滚**：从 `~/.zhuoh-agent-backup/<时间戳>/<宿主>/` 按原相对路径取回备份文件放回即可。
