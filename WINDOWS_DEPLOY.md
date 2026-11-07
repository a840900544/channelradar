# Windows 云电脑迁移

通过 GitHub 接续开发时，先克隆私有仓库并在云电脑 Codex 中打开该目录。阅读 `AGENTS.md` 和 `HANDOFF.md`。将 Windows 迁移包解压到单独目录，再将其中的 `channelradar.sqlite3`、`data/workbench.sqlite3` 和 `frontend/dist` 复制到新克隆目录的对应位置。两个数据库用于恢复实验与审核记录，构建产物可直接启动页面。保留 Git 克隆得到的源码。

如需在没有迁移包时从源码构建页面，在云电脑安装 Node.js 22.12+，在 `frontend` 目录运行 `npm ci` 和 `npm run build`。数据库由初始化和采集步骤重新建立。

1. 在云电脑安装 Python 3.12 或以上版本，并确认 PowerShell 中的 `python --version` 可运行。
2. 将迁移包复制到云电脑并解压。在解压目录打开 PowerShell，执行以下命令。

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start-windows.ps1
   ```

3. 首次启动会要求设置至少 12 位的管理员密码。在云电脑的浏览器打开 http://127.0.0.1:8000/，以 `admin` 登录。保持启动窗口运行。

迁移包含已构建的页面、采集数据库和工作台数据库。迁移包含已有帖子摘要和跟进记录，请用私人文件传输。管理员配置和 QQ 登录凭据在目标机器重新建立。通过远程桌面使用时，浏览器与服务均运行在云电脑上。

如需继续采集，请在云电脑安装腾讯官方频道 CLI 并完成授权。在项目目录用实际 CLI 路径和已授权公开频道 ID 执行一次联调。

```powershell
.\.venv\Scripts\python.exe -m radar.worker --cli C:\Tools\tencent-channel-cli.exe --guild 631030283978486639 --once
```

联调通过后，去掉 `--once` 可在当前窗口持续运行。默认每轮结束后等待 15 分钟。公网直接访问需要另行配置 HTTPS 入口。
