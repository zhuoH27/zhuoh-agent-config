# 同步指令
把下面整段发给已经配置过本仓库的 agent（fork 本仓库的人请把 URL 换成自己的仓库地址）：

```text
请把当前宿主配置同步到仓库最新版：
1. 在新的临时目录重新克隆 https://github.com/zhuoH27/zhuoh-agent-config.git，记录 git rev-parse HEAD。
2. 若我告诉你上次安装的 commit，先给我看 git log --oneline <上次>..HEAD 和 git diff <上次>..HEAD --stat；不知道上次 commit 就说明并跳过。
3. 运行 python scripts/agent_sync.py setup --dry-run --target <claude|codex|both>，把将变更的文件、区块差异和备份清单给我确认（若本机无 Python，兜底脚本 install.ps1 不支持 --dry-run 且会整文件覆盖规则文件，请先向我说明并确认后再决定是否执行）。
4. 我明确批准后运行同款命令（去掉 --dry-run；无 Python 时用 powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --target <...>），再运行 python scripts/agent_sync.py doctor --target <...>，把结果贴给我。
5. 若 dry-run 出现 [警告]（疑似旧版铁律、标记异常等）停下，由我决定处理方式；被权限/沙箱拒绝时停止汇报，不要换工具或路径绕过；不要删除旧 Skill 或 ~/.zhuoh-agent-backup 里的备份。
```

维护本仓库时（改了规则或技能后发布）：对 Agent 说 **“同步配置”**，它会按 `skills/zhuoh-config-sync/SKILL.md` 的闭环执行 doctor → audit → pytest → 变更摘要 → 确认后提交，`git push` 前必须获你批准。
