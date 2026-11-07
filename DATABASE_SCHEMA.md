# 数据库设计

工作台已通过 SQLAlchemy 与 Alembic 初始化 `posts`、`leads`、`lead_feedback`、`audit_logs`、`admin_sessions`。同一来源、频道、帖子联合唯一，每帖对应一个审核记录。内容哈希用于识别更新，审核版本用于检测并发覆盖。会话表只保存随机会话的哈希及过期时间。工作台按现有配置可使用独立 SQLite 或 PostgreSQL 数据库，采集实验库继续通过只读连接导入。

以下为 PostgreSQL 目标模型。CLI 切片先在 SQLite 实现高校、候选频道及版块。

| 实体 | 核心字段及约束 |
| --- | --- |
| universities | id、名称、地区、简称、校区、别名，名称唯一 |
| campus_channels | university_id、provider、external_id、简介、链接、匹配证据、审核及访问状态，三者联合唯一 |
| channel_sections | campus_channel_id、external_id、名称、类型、监测状态、游标，前两者联合唯一 |
| keywords | 类别、关键词、规则方向、启用，类别和归一化词及方向联合唯一 |
| scan_jobs | provider、目标、状态、租约、起止时间、请求次数、耗时、脱敏错误；活动任务按目标唯一 |
| posts | provider、频道及帖子 ID、来源链接、必要文本、时间、哈希，按来源和帖子标识幂等 |
| leads | post_id 唯一、分数、优先级、排除原因、处理状态、备注 |
| lead_analysis | lead_id、正文哈希、模型、提示词版本、结构化判断、用量，按分析版本去重 |
| lead_feedback | lead_id、analysis_id、审核人、结论、时间 |
| notifications | lead_id、通道、事件版本、状态、尝试次数、下次尝试时间，前三者联合唯一 |
| settings | key 唯一、类型化 JSON、更新时间；密钥只保存引用 |
| audit_logs | 操作者、动作、目标、结果、时间；避免正文和凭据 |

目标保留策略为正文默认 30 天、任务日志 30 天、商机及反馈 90 天、审计 180 天，支持撤销授权后按频道删除和清理衍生记录。默认舍弃作者标识与附件。备份按独立生命周期轮换并验证恢复。
