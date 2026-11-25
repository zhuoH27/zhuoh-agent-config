---
name: zhuoh-config-sync
description: "用户要求同步配置、更新配置、检查配置同步状态、备份 Agent 配置，或维护 zhuoh-agent-config 仓库（改规则/技能后发布）时触发，执行 doctor 体检、audit 安全门禁、pytest 测试、变更摘要展示与确认后提交/推送的标准闭环；仅查询无关状态或与本仓库维护无关的任务不触发。"
---
# 配置同步与自维护闭环

> 核心思想：Agent 负责 体检 → 门禁 → 测试 → 变更摘要 → 确认后提交/推送；任何覆盖宿主配置、本地提交与远端推送都把决定权留给人。

## 触发词
“同步配置”、“更新配置”、“备份 Agent 配置”、“检查配置同步”、`/sync`。

## 标准执行闭环（SOP）

执行前先定位仓库根（含 `manifest.json` 的目录），全部命令在仓库根运行：

1. **健康体检**：`python scripts/agent_sync.py doctor --target auto`
   - 输出 `[警告]` 时停下：向用户展示宿主端与仓库的差异，确认后先 `setup --dry-run` 再覆盖更新（更新前自动分层备份至 `~/.zhuoh-agent-backup/<TS>/<host>/...`），禁止未经确认直接覆盖。
   - 权限或沙箱拒绝时停止汇报，不换工具或路径绕过。
2. **安全门禁**：`python scripts/agent_sync.py audit`
   - 出现 `[FAIL]`（疑似密钥、硬编码本地路径、非 UTF-8 文本、缺 SKILL.md、frontmatter 缺失）必须先修复再继续；`[提示]`（技能超 10KB 建议拆层）记录后可继续。
3. **回归测试**：`python -m pytest tests/ -q`（缺失 pytest 时先 `python -m pip install pytest`）
   - 任何失败停下修复；测试全部走 `--home`/`--repo` 沙盒，不触碰真实配置。
4. **变更摘要**：`git status -s` 与 `git diff --stat`，用 3–5 行概括本次改动（涉及的规则、技能、代码与新增文件）。
5. **受控提交与推送**：
   - 先展示拟提交文件清单与 commit message（中英均可，说明动机），**获用户确认后**再执行 `git add`（仅添加本次任务改动文件，严禁裸 `git add -A`/`.`）+ `git commit`（对齐铁律第 2 条，不擅自打包用户原有改动）。
   - **`git push`（外发）与任何删除操作前，必须获得用户针对该操作的明确确认**（铁律第 1 条）；未批准则停在本地 commit。

## 轻量分支（仅备份或看状态）
用户只想备份配置或查看同步状态时，只运行 `doctor --target auto` 与 `status` 展示现状；如需手动备份宿主既有文件，按 `<TS>/<host>/<相对目录>/<原名>_<TS>.<ext>.bak` 放入 `~/.zhuoh-agent-backup/`（重名 `_2`/`_3`；引擎无 `backup` 子命令，不得虚构命令）；此类请求不改动仓库，不执行 `git add`/`git commit`。

## 命令速查（`scripts/agent_sync.py`，内部实现在 `scripts/sync_lib/`）
| 命令 | 用途 |
|---|---|
| `setup [--dry-run] --target <auto\|claude\|codex\|agents\|both> [--mode <append\|replace\|abort>] [--skill-mode <copy\|link>] [--home 目录]` | 安装/覆盖更新宿主配置（含 `SKILL.md`、`references/` 与 `prompts/`）；copy 为默认，link 为实验性 |
| `doctor --target <...>` | 体检：规则、技能（含 `references/`）、Codex `prompts/` 一致性与链接健康 |
| `audit` | 推送前门禁：扫描密钥、硬编码路径、非 UTF-8 编码与各技能 SKILL.md/frontmatter/体积 |
| `status [--json]` | 当前模式与各宿主实际已装规则/技能/提示词摘要 |

## 硬性边界
- 平台：仅维护 Windows（PowerShell 5.1+ / pwsh 7 + Python 3）；不重新引入 POSIX `install.sh` 或非 Windows CI。
- 备份统一按 `~/.zhuoh-agent-backup/<TS>/<host>/<相对目录>/<原名>_<TS>.<ext>.bak`（重名 `_2`/`_3`）存放；不覆盖旧备份、不改 `.bak`。此备份根供安装器写宿主配置用，与铁律第 2 条的项目内 `_backup/` 并存不混用。
- 不删除宿主里的第三方技能及技能目录内额外文件；功能重叠仅提醒。
- 换行沿用目标原文件；写入 UTF-8 无 BOM；非法 UTF-8 报错停止。
- 铁律第 1、2、3 条全程生效。

## 新机初始化
用户要求按 `BOOTSTRAP.md` 配置本机环境时：阅读 `BOOTSTRAP.md`（先审阅 `scripts/agent_sync.py`、`scripts/sync_lib/*.py` 与 `install.ps1`），执行 dry-run → 展示计划 → 获批准 → apply → doctor 校验 → 汇报（含 commit hash）。
