# 同步指令
把下面整段发给已经配置过本仓库的 agent（fork 本仓库的人请把 URL 换成自己的仓库地址）：

```text
请把当前宿主配置同步到仓库最新版：
1. 在新的临时目录重新克隆 https://github.com/zhuoH27/zhuoh-agent-config.git，记录 git rev-parse HEAD。
2. 若我告诉你上次安装的 commit，先给我看 git log --oneline <上次>..HEAD 和 git diff <上次>..HEAD --stat，并说明 install.sh / install.ps1 是否有改动；不知道上次 commit 就说明并跳过。
3. 运行安装器 dry-run（macOS/Linux：sh install.sh --dry-run --target <claude|codex|both>；Windows：powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 --dry-run --target <claude|codex|both>），把将变更的文件、区块差异和备份清单给我确认。
4. 我明确批准后运行 --apply，再运行 --verify，把结果贴给我。
只改仓库来源，不直接手改宿主配置；不要删除旧 Skill 或 _backup；dry-run 出现 [警告] 或被权限/沙箱拒绝就停下，不要绕过。
```
