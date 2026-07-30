# 当前开发状态

- 当前里程碑：M0 业务数据与 Java 接口
- 当前子阶段：M0.3 固定业务数据（已完成）
- 已完成任务：T001～T024
- 当前场景：Flyway V2 固定初始化 `ORDER-001`～`ORDER-005`，包含 5 个任务、5 个步骤、3 个质检问题、3 个复核记录和 5 个交付记录；`ORDER-003` 黄金链路已固化且尚无返工任务
- 通过测试：Maven 全量测试 15/15；M0.3 根级 `make test-business-data` 7/7；M0.2 回归 7/7；重置脚本连续两次得到 5 个订单和相同快照 `d57e54c32e4ef26eb01c76a8ed97a0ce`；三服务冒烟与基础配置检查通过
- 失败测试：最终结果 0；开发中按测试先行确认空数据库映射测试失败，并修复旧 Repository 测试占用固定 ID、多个 DataJpa 测试复用已停止 Testcontainer 的问题
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16；Homebrew 安装 Maven 时另安装 OpenJDK 26.0.2 作为其依赖，但项目和 Shell 继续固定使用 JDK 21
- 最近治理更新：DOC-003 已建立 Agent 面试价值门禁；每次开发先评估，只有确有面试价值时才更新 `doc/needCare.md`
- 下一任务：T025 实现 `GET /api/orders/{id}` 的正常与 404 查询契约
