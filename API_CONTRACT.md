# 管理接口契约

## 已运行的工作台接口

| 方法与路径 | 行为 |
| --- | --- |
| GET /healthz、GET /readyz | 存活与数据库就绪检查 |
| POST /api/v1/session | 管理员登录，返回 CSRF 值并设置会话 Cookie |
| GET /api/v1/session | 恢复当前已登录会话及 CSRF 值 |
| DELETE /api/v1/session | 注销并在数据库撤销会话 |
| POST /api/v1/imports/experiments | 从服务端指定的完整日采集库导入，返回新增、更新和读取计数 |
| GET /api/v1/dashboard | 导入帖子、规则候选、人工确认、成交金额和高校分布 |
| GET /api/v1/leads | 按队列范围、高校、状态和内容分页查询 |
| GET /api/v1/leads/{id} | 脱敏摘要、原帖、来源频道、承接状态和反馈历史 |
| POST /api/v1/leads/{id}/feedback | 保存带版本的审核、跟进状态、备注、反馈标签及成交金额 |
| GET /api/v1/scan-jobs | 查看完整日采集范围、翻页数和覆盖状态 |

登录使用 HttpOnly、SameSite Strict Cookie，默认启用 Secure。登录和健康检查之外的数据接口要求管理员会话，写接口要求 `X-CSRF-Token`。单进程限制同来源 15 分钟内 5 次失败登录。审核记录被更新时返回 409。确认可承接后才能记录有效商机、已跟进或成交，排除结论与成交金额分别校验。

## 后续契约

以下包含既有接口的扩展目标与尚待实现的管理能力。

| 方法与路径 | 语义 |
| --- | --- |
| GET /healthz | 进程存活 |
| GET /readyz | 数据库可用 |
| POST /api/v1/session | 登录，失败限速 |
| DELETE /api/v1/session | 注销 |
| GET /api/v1/dashboard | 指定时区的帖子、商机、运行和用量统计 |
| GET /api/v1/universities | 按正式名、简称、校区或别名搜索 |
| POST /api/v1/universities/{id}/discovery-jobs | 创建发现任务，返回 202 和任务 ID |
| GET /api/v1/channels | 按高校、来源、审核及访问状态筛选 |
| PATCH /api/v1/channels/{id}/review | 保存审核结论、授权范围及审计 |
| GET /api/v1/channels/{id}/sections | 读取已存版块，支持更新监测策略 |
| GET /api/v1/leads | 按高校、频道、类别、时间、评分和状态筛选 |
| GET /api/v1/leads/{id} | 来源、摘要、模型证据与处理历史 |
| POST /api/v1/leads/{id}/feedback | 记录人工标注和备注 |
| GET /api/v1/scan-jobs | 运行历史、脱敏错误和用量 |
| GET、POST /api/v1/keywords | 查询与新增规则，单项 PATCH 更新和禁用 |
| GET、PATCH /api/v1/settings/{group} | AI、评分和通知配置，响应隐藏密钥 |
