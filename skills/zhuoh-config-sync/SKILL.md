---
name: zhuoh-config-sync
description: "用户要求同步配置、更新配置、检查配置同步状态、备份 Agent 配置，或维护 zhuoh-agent-config 仓库（改规则/技能后发布）时触发，执行 doctor 体检、audit 安全门禁、pytest 测试、变更摘要展示与推送前确认的标准闭环；仅查询状态或与本仓库维护无关的任务不触发。"
---
# 配置同步与自维护闭环

> 核心思想：配置仓库的日常维护是一句话的事。Agent 负责 体检 → 门禁 → 测试 → 摘要 → 受控提交 五步闭环；唯一必须留给人的决策是“是否推送”与“如何覆盖更新”。

## 触发词
“同步配置”、“更新配置”、“备份 Agent 配置”、“检查配置同步”、`/sync`。

## 标准执行闭环（SOP）

执行前先定位仓库根（含 `manifest.json` 的目录），全部命令在仓库根运行：

1. **健康体检**：`python scripts/agent_sync.py doctor --target auto`
   - 输出 `[警告]` 时停下：向用户展示宿主端与仓库的差异，确认后先 `setup --dry-run` 再覆盖更新（更新前自动备份至 `~/.zhuoh-agent-backup/`），禁止未经确认直接覆盖。
   - 权限或沙箱拒绝时停止汇报，不换工具或路径绕过。
2. **安全门禁**：`python scripts/agent_sync.py audit`
   - 出现 `[FAIL]`（疑似密钥、硬编码本地路径、frontmatter 缺失）必须先修复再继续；`[提示]`（技能超 10KB 建议拆层）可记录后继续。
3. **回归测试**：`python -m pytest tests/ -q`
   - 任何失败停下修复；测试不得触碰真实 `~/.claude` 或 `~/.codex`（全部走 `--home`/`--repo` 沙盒）。
4. **变更摘要**：`git status -s` 与 `git diff --stat`，用 3–5 行向用户概括本次改动（哪些规则、哪些技能、是否新增文件）。
5. **受控提交与推送**：
   - 生成规范 commit message（中英均可，说明动机），执行 `git add` + `git commit`。
   - **`git push`（外发）与任何删除操作前，必须获得用户针对该操作的明确确认**（铁律第 1 条）。
   - 用户未批准时停在本地 commit，不推送。

## 命令速查（`scripts/agent_sync.py`）
| 命令 | 用途 |
|---|---|
| `setup [--dry-run] --target <auto\|claude\|codex\|agents\|both> [--mode <append\|replace\|abort>] [--skill-mode <copy\|link>] [--home 目录]` | 安装/覆盖更新宿主配置（含 `SKILL.md` 与 `references/`）；copy 模式为默认（安全），link 模式实验性 |
| `doctor --target <...>` | 体检：规则/技能（含 `references/`）一致性、链接健康 |
| `audit` | 推送前门禁：全量扫描密钥、硬编码路径、frontmatter、技能体积 |
| `status [--json]` | 当前模式、各宿主同步状态摘要 |

## 硬性边界
- 平台：仅维护 Windows（PowerShell 5.1+ / pwsh 7 + Python 3）；不提供 macOS/Linux 入口，不得重新引入 sh 入口或非 Windows CI。
- 备份统一在 `~/.zhuoh-agent-backup/<YYYYMMDD_HHMMSS>/`，命名 `<原名>_<TS>.<ext>.bak`（重名 `_2`/`_3`）；不覆盖旧备份；不修改 `.bak` 文件。
- 不删除宿主里本仓库不管理的第三方技能（如 `academic-pptx`、`anti-defensive-writing`）及技能目录内的额外文件；功能重叠仅提醒。
- 换行沿用目标原文件；写入 UTF-8 无 BOM；非法 UTF-8（GBK/UTF-16）报错停止。
- 铁律第 1、2、3 条全程生效：不可逆操作先确认；修改前可恢复；只报告真实执行过的操作。

## 新机初始化
用户说“按 BOOTSTRAP.md 配置本机环境”或“配置本机环境”时：阅读 `BOOTSTRAP.md`，执行 dry-run → 展示计划 → 获批准 → apply → doctor 校验 → 汇报（含 commit hash）。
