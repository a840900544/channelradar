# 获客系统公开项目调研

核查日期为 2026-11-07。已克隆五个公开仓库并读取许可证和相关源码。本轮运行验证仅针对 ChannelRadar，参考项目的部署、外部接口、费用和实际获客效果均未实测。GitHub 元数据 API 返回 403 配额限制，以下维护证据使用 Git 提交日期。

| 项目 | 许可证与所核查提交 | 适合参考的部分 |
| --- | --- | --- |
| [Lead Signal Listener](https://github.com/yangyixxxx/lead-signal-listener) | MIT，983fd7b，2026-10-10 | 规则痛点/意向评分、来源去重、人工状态和备注、列表筛选 |
| [Social Demand Signal Agent](https://github.com/jackterror/social-demand-signal-agent) | MIT，0844079，2026-07-07 | 来源、时效、排除原因、人工审核、结果事件闭环 |
| [Subreach](https://github.com/niihhhall/subreach) | MIT，03ab3d0，2026-11-01 | 需求方/建议者/供应方角色区分，匹配与意向分开判断，阶段状态 |
| [OpenMagpie](https://github.com/obris-dev/openmagpie) | Apache-2.0，包含 ee/ 及第三方组件例外，9967975，2026-10-14 | Watch、回填窗口、语义过滤与 Webhook 配置 |
| [BizRadar](https://github.com/datascale-ai/BizRadar) | MIT，f296994，2026-05-16 | Pydantic 结构化痛点提取、多步骤复核和通知 |

## 源码证据与适用性

Lead Signal Listener 的规则评分主要位于 [listener/scoring.py](https://github.com/yangyixxxx/lead-signal-listener/blob/983fd7b6b09dc076de964632e6e6e8bf63d33981/listener/scoring.py)，来源和唯一约束位于 [listener/store.py](https://github.com/yangyixxxx/lead-signal-listener/blob/983fd7b6b09dc076de964632e6e6e8bf63d33981/listener/store.py)。它提供轻量线索管理思路，现有评分仍是词法规则，实际中文漏报改善需要另做实验。

Social Demand Signal Agent 的 [pipeline.py](https://github.com/jackterror/social-demand-signal-agent/blob/08440799afbd2803ccc1e9f8d26cebf94e11837e/scripts/sdsa/pipeline.py) 包含相关度、时效、排除和路由判断，[storage.py](https://github.com/jackterror/social-demand-signal-agent/blob/08440799afbd2803ccc1e9f8d26cebf94e11837e/scripts/sdsa/storage.py) 保存审核与结果事件。可借鉴证据与反馈闭环，避免只按发帖量评估渠道。

Subreach 的 [models.py](https://github.com/niihhhall/subreach/blob/03ab3d0f7c90c0ec4f361d4d33595706363882a0/reddit_outreach/models.py) 将匹配分、意向分、是否需求方和角色分开建模。仓库包含发送与私信阶段，接入文档依赖 Zernio 等服务。ChannelRadar 沿用管理员人工跟进的产品范围。

OpenMagpie 的 [semantic_filter.py](https://github.com/obris-dev/openmagpie/blob/9967975d0f9625133176fb76898a8f436bd4bc46/packages/openmagpie-schema/src/openmagpie_schema/watch_actions/semantic_filter.py) 与 [watch/_runs.py](https://github.com/obris-dev/openmagpie/blob/9967975d0f9625133176fb76898a8f436bd4bc46/packages/openmagpie-schema/src/openmagpie_schema/watch/_runs.py) 展示了监测动作和运行记录的模型。使用任何代码前需逐目录检查 [许可证](https://github.com/obris-dev/openmagpie/blob/9967975d0f9625133176fb76898a8f436bd4bc46/LICENSE)。

BizRadar 的 [extractor_agent.py](https://github.com/datascale-ai/BizRadar/blob/f296994e515ef6aae5017dd2c37cfcb016a28432/core/agents/extractor_agent.py) 使用结构化结果提取痛点。其主要业务是产品点子评估，与校园技能服务的当下需求存在差异，适合参考结构化判断方式。

## 产品落地

ChannelRadar 采用架构参考，新增代码独立实现。已验证的 QQ 官方 Provider 继续负责接入，工作台承接需求审核、可承接判断、人工跟进、成交记录与筛选反馈。当前后台使用 FastAPI、SQLAlchemy 2、Alembic，前端为 Vue 3、TypeScript、Vite 与 Element Plus。

本轮实现人工审核闭环，AI 语义识别、Embedding、图片识别、企业微信和自动调度仍在实施范围内。衡量顺序为有效需求密度、人工认可率、发现延迟、请求成本和人工记录的转化结果。付费意向未知的候选保留待核实状态。
