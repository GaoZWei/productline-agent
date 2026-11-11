# 文档总导航

这里统一收纳项目说明、开发计划、演示记录、学习资料和面试材料。首次了解项目可按“当前状态 → 系统全链路 → 演示与模块说明”阅读；开发时遵守[开发规则](../AGENTS.md)，只读取当前任务所需章节。

## 按用途阅读

| 用途 | 文档 | 内容与边界 |
|---|---|---|
| 当前进度 | [STATUS](STATUS.md) | 当前阶段、实际验证、阻塞和下一最小任务的统一入口 |
| 里程碑 | [ROADMAP](ROADMAP.md) | 里程碑状态；不代替当前批次说明 |
| 系统调用链 | [系统全链路与业务分支](architecture/SYSTEM_FLOW.md) | 三端职责、查询、诊断、RAG 和两次独立人工确认 |
| 业务模型 | [领域模型](architecture/DOMAIN_MODEL.md) | 订单、任务、问题、复核及交付关系 |
| 流程图片 | [业务流程图](architecture/flow/README.md) | 业务阶段与系统执行总览，注明适用边界 |
| Java 接口 | [API 契约](api/API_CONTRACT.md) | 业务查询、响应和写入契约 |
| 返工生命周期 | [M8契约v1](api/REWORK_CONTRACT.md) | M8.1～M8.4已验收，T821/T822离线验收通过；内部只读Tool及三端确认尚未生产装配 |
| 演示记录 | [ORDER-003 演示链路](demo/AGENT_DEMO_FLOW.md) | 2026-10-22 的已发生记录及原始快照，不代表当前运行库状态 |
| 固定场景 | [演示数据](demo/DEMO_DATA.md) | 固定 ID、30 单场景与黄金链路 |
| 重复演示 | [重置手册](demo/DEMO_RESET.md) | 数据清除、证据保留及恢复步骤 |
| 总体规划 | [总体计划](planning/plan.md) | 目标、架构和里程碑设计，规划不等于已实现 |
| 当前任务设计 | [详细计划](planning/detailed-plan.md) | 按任务读取对应阶段；KB 批次以知识库需求与 STATUS 为准 |
| 功能历史 | [开发记录](development/record.md) | 已交付核心功能的历史记录，不收录纯文档整理 |
| 知识库 | [知识库文档导航](knowledge/README.md) | 需求、资料台账、授权、存储与管理设计 |
| 规范语料 | [固定规范目录](../knowledge-base/README.md) | 实际规范正文与 catalog；管理和面试文档不参与检索 |
| 面试准备 | [准备计划与固定流程](interview/Agent-Question-Plan.md) | 问题讨论、成熟答案和优化事项的维护流程 |
| 面试清单 | [准备清单](interview/Agent-interview.md) | 已验证事项与待办；Q39、Q40 继续暂缓 |
| 题库与答案 | [主问题](interview/Agent-Question.md)、[扩展问题](interview/Agent-Question-Extend.md)、[成熟答案](interview/Agent-Answer.md) | 主问题、追问和已认可答案；题目进度以准备计划为准 |
| 面试工程要点 | [关注点](interview/needCare.md)、[优化事项](interview/Agent-Optimization.md) | 已有工程价值、当前边界及待验证事项 |
| 简历与项目图片 | [简历 PDF](<interview/assets/AI Agent CV（9.13）.pdf>)、[agent项目.png](interview/assets/agent项目.png) | 面试原始附件，不能据其推断已实现或已验证能力 |
| 工程学习 | [Python 学习手册](learning/pythonKnowledge.md)、[Agent 开发学习 PDF](<interview/assets/AI Agent 开发（云老师结合版）11.2.pdf>) | 手册主要对应 M1.1～M2.8；PDF 为学习附件，不作为当前实现依据 |
| 历史架构 | [M0～M4 思维导图](archive/system-mindmap-m0-m4.md) | 2026-08-22 的历史快照，不作为当前系统现状 |

## 模块入口

- [Agent 服务](../agent-service/README.md)：模型配置、Tool、Workflow、知识库、Approval、观测与局部验收命令。
- [Java 业务服务](../business-service/README.md)：业务查询与写入、授权、版本和幂等契约。
- [Web 控制台](../agent-frontend/README.md)：统一 Agent 页面、跨订单续接、SSE、人工确认与前端开发。
- [仓库首页](../README.md)：环境、启动方式与常用命令。

## 文档维护规则

- 新项目文档按用途放入 `planning/`、`architecture/`、`api/`、`development/`、`demo/` 或 `knowledge/`；学习材料放入 `learning/`，面试材料与附件放入 `interview/`，历史快照放入 `archive/`。
- 当前进度、实际测试和下一任务统一维护在 STATUS；首页和模块 README 只保留职责与使用说明，不复制累计进度。
- 带日期、任务编号的历史记录保留当时事实；涉及早期边界时明确阶段，不通过改写历史制造当前能力。
- 移动文档时同步本地链接、图片、锚点、源码引用、开发规则及检查脚本；后续不恢复旧 `doc/` 或根目录面试材料副本。
- 实际业务能力以实现及验证为依据；规划、学习资料、简历和受控评测都不能证明线上质量。详细开发与文档门禁见 [AGENTS.md](../AGENTS.md)。
