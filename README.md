# ChannelRadar

## 获客工作台

工作台提供已采集需求的筛选、原帖核查、承接判断、人工跟进、成交金额和反馈历史。当前导入的是已完成整日实验的官方 QQ Feed 摘要，来源短链会用现有核查记录补齐。商机队列包括规则候选和人工纳入跟进的记录。切换到全部帖子可复核漏筛。

### 本机启动

需要 Python 3.12+ 和 Node.js。先安装依赖、构建前端，再初始化配置和数据库。Windows 可用 `.venv/Scripts/python`，Linux 可用 `.venv/bin/python`。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cd frontend
npm ci
npm run build
cd ..
python -m radar.cli init --local
python -m uvicorn radar.api:create_app --factory --host 127.0.0.1 --port 8000
```

访问 http://127.0.0.1:8000，登录后点「导入采集结果」。默认管理员用户名为 `admin`，初始化时设置密码。也可加 `--generate`，随机密码写入本机忽略目录 `data/admin-initial.txt`。已存在 `.env` 时用 `python -m radar.cli migrate` 升级数据库。账号或会话密钥不进入前端构建产物。

服务器固定读取 `RADAR_SOURCE_DB` 指向的采集 SQLite 库，默认项目根目录的 `channelradar.sqlite3`。采集库只读，工作台审核数据默认写入 `data/workbench.sqlite3`。导入可重试，内容变化会使承接判断回到待核实，历史跟进记录继续保留。

`python -m unittest -v` 验证 CLI 与工作台接口。Windows 本机服务已启动且初始化时选择生成密码时，可运行 `python scripts/browser_smoke.py` 做隔离的浏览器验收。

### Ubuntu 工作台部署

项目包含 [Dockerfile](Dockerfile)、[Compose](docker-compose.yml)、[Nginx](deploy/nginx.conf) 与 [备份脚本](deploy/backup.sh)。生产部署需准备一致的采集库快照 `channelradar.sqlite3` 和 `.env`，配置随机的 `RADAR_POSTGRES_PASSWORD`、管理员密码哈希与会话密钥。默认登录 Cookie 要求 HTTPS。运行 `docker compose up -d --build` 后，工作台由 Nginx 提供在宿主机 `127.0.0.1:8080`，域名 HTTPS 反代指向该地址。API 启动时先执行 Alembic 迁移，PostgreSQL、API 均设健康检查，各服务日志自动轮换。

运行 `bash deploy/backup.sh` 可得到权限受限的 PostgreSQL 压缩备份。定期把备份恢复到独立测试库，确认表结构与记录可读取。备份保留周期由部署方配置。

目前已实测本机 SQLite 迁移和浏览器工作流，生成过 PostgreSQL 离线迁移 SQL。Ubuntu Compose 的实际容器运行尚未验证。Worker、语义识别、自动调度、企业微信和工作台库的自动保留期清理仍待接入。

高校频道发现 CLI，需要 Python 3.12+，仅使用标准库。默认运行模拟数据。示例为新建数据库，后续命令中的 `1` 请替换为实际候选 ID。

```bash
python channelradar.py universities 深大
python channelradar.py discover 深圳大学
python channelradar.py review 1 approved --access public --note "仅模拟演示"
python channelradar.py sections 1
python -m unittest -v
```

候选默认待审核，访问状态为未知。批准后可查询版块，再次发现会保留审核结论。拒绝可撤销访问并清除已存版块。试点学校、别名和校区位于 `universities.csv`。SQLite 文件默认写入当前目录，支持用 `--db` 隔离环境。限制数据库文件的本机访问权限。

## 腾讯 CLI 接入验证

扩校可运行 `python expand_pilots.py --cli /path/to/tencent-channel-cli --school 江西科技学院 --school 南昌工学院 --date 2026-11-06 --out expansion.json`。每校从搜索首页命中的前三个同名频道中，选择官方标记为公开且成员数最多的一个做整日扫描。成员数只用于入口排序，报告中的日内发帖量用于后续活跃度判断。频道名称匹配不代表学校官方认证。成功的历史日实验会复用，失败任务可重跑，报告以临时文件替换方式更新。

加 `--prefer-active` 会先比较前三个公开候选首页的近 24 小时帖子数量及时间跨度，优先选择近期发帖密集的入口。首页数据只用于选入口，最终活跃资格以完整日扫描结果和 `--min-daily-posts` 阈值确认，默认每天 50 条。本轮实验阈值可调整，不代表学校整体活跃度。

整日采集和扩校入口默认 `--page-size 100`，该主页页大小已通过真实接口及跨页对照验证。其他 Provider 调用默认仍为 20，版块页大小保持已验证的 20。改变页大小不改变时间边界和去重条件。

完整自然日实验使用 `python scan_day.py --cli /path/to/tencent-channel-cli --guild GUILD_ID --date 2026-11-06 --out report.json`。日期按北京时间，仅支持已结束且在最近 30 天内的自然日。脚本从最新页往前翻，按帖子 ID 去重；直到接口结束或连续两整页早于起始零点，才标记已到时间边界。单页旧帖不会中止扫描。

每页和游标一起提交 SQLite，网络失败或本次页数预算耗尽后，原命令可继续。默认每频道本次最多 300 页，未到边界会明确标记未完成并返回非零退出码。覆盖状态仅代表官方最新 Feed 的可访问时间线，删除、权限不可见以及仅图片中的需求仍可能影响结果。实验为人工复核保存脱敏标题与摘要，运行时自动清除 30 天前的日实验数据。数据库不保存作者资料。

用 `python experiment.py --cli /path/to/tencent-channel-cli --guild GUILD_ID --out report.json` 可对官方标记为公开的频道做有界抽样。单轮最多 8 个频道，每频道读取资料、最新一页和版块列表，报告近 24 小时样本数、技术词提及量和待审核项。近 24 小时样本数受首页大小限制，不能当作完整日发帖量。候选标题会脱敏保存，请按本机权限保护报告。

对已获准的频道做单次最新帖扫描，可运行 `python scan_latest.py --cli /path/to/tencent-channel-cli --guild GUILD_ID --authorized`。传 `--section SECTION_ID` 可定向扫描版块。每次从最新页开始，至少重叠两页（若还有下一页），最多扫描三页，可用 `--max-pages` 调整为 2 至 6。出现 `page_cap` 表示扫描触及页数上限，可能有覆盖缺口。

SQLite 保存帖子 ID、摘要哈希、首次观察时间和扫描记录。仅在当前来源的一整页均已见时提前停止，避免一条重复或置顶帖截断扫描。候选输出仅供人工审核，规则能识别部分无「求助」「有偿」字眼的问题描述，语义模型和自动调度待实现。建议同一数据库中的扫描串行执行。

官方二进制可先执行 `version`、`schema manage.search-guild-content` 和 `schema manage.get-guild-channel-list`。真实测试须在明确账号、允许的搜索与频道范围后，由管理员按官方流程独立授权。适配器通过 `--tencent-cli /absolute/path/to/tencent-channel-cli` 显式启用。当前其响应映射仅用合成数据验证，遇到未知格式会中止。

已实现的采集与审核工作台，以及后续识别和部署任务见 [实施计划](IMPLEMENTATION_PLAN.md)。真实与合成证据的边界见 [接入调研](RESEARCH.md)，公开获客项目见 [源码调研](OPEN_SOURCE_REVIEW.md)。
