# 当前开发状态

- 当前里程碑：M0 业务数据与 Java 接口
- 当前子阶段：M0.7 故障模拟（已完成）
- 已完成任务：T001～T049
- 当前场景：开发环境可对只读 `/api` 请求确定性注入延迟、客户端超时、统一 500、缺失 `data` 的非法响应和 403；功能默认关闭且不作用于写接口
- 通过测试：Maven 全量测试 56/56；M0.7 根级 `make test-java-faults` 8/8；M0.4～M0.7 联合回归 41/41；`make test` 的基础检查、三服务冒烟及 M0.2～M0.7 分阶段验收全部通过
- 失败测试：最终结果 0；测试先行首次运行 M0.7 的 7 个用例时 6 个失败、1 个通过，失败证明模拟尚不存在，默认关闭保护已成立；实现并增加写接口隔离用例后 8/8 通过
- 当前阻塞：无
- 开发环境：OpenJDK 21.0.12、Maven 3.9.16；Homebrew 安装 Maven 时另安装 OpenJDK 26.0.2 作为其依赖，但项目和 Shell 继续固定使用 JDK 21
- 最近治理更新：DOC-003 已建立 Agent 面试价值门禁；每次开发先评估，只有确有面试价值时才更新 `doc/needCare.md`
- 已知非阻塞问题：故障模拟通过阻塞 Servlet 线程制造延迟，只适合受控开发测试；Python Client 尚未实现，因此尚未验证 `TOOL_TIMEOUT`/`RESPONSE_VALIDATION_ERROR` 映射和重试策略；`X-User-Id`/`X-User-Role` 仍非真实认证；Trace ID 尚未串联 Python Run/Step
- 下一任务：T050 初始化 Vue 3 项目
