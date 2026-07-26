# 测试报告

## M0.1 项目基础环境

- 验证时间：2026-07-26
- `make help`：通过，显示 13 个根级开发命令
- `docker compose config`：通过，PostgreSQL、Java、Python、Web 四项服务配置有效
- `make test`：通过
  - 必需目录、文件和环境变量检查：1 组通过
  - Agent Service 健康检查：通过
  - Business Service 健康检查：通过（本机无 JDK，使用 Docker）
  - Web Console 健康检查：通过
- `docker compose up --detach --build`：通过
  - PostgreSQL：`healthy`
  - Java/Python/Web：容器均为 `Up`
  - 三个 HTTP `/health`：均返回 `status=UP`
- 环境切换检查：通过，自定义 PostgreSQL、Java、Python、Web 四个宿主端口均由环境变量正确展开
- 静态语法检查：
  - `python3 -m py_compile agent-service/app/main.py`：通过
  - `node --check web-console/server.mjs`：通过
  - `git diff --check`：通过
- 开发中失败与修复：首次 `make test` 因 macOS `/usr/bin/java` 占位程序被误认为有效 JDK 而失败；改为实际执行 `java -version`/`javac -version` 后回退到 Docker，完整复测通过
- 业务测试：不适用（M0.1 尚无业务逻辑）

## 开发环境维护 ENV-001

- 验证时间：2026-07-26
- `brew list --versions openjdk@21`：通过，版本 `21.0.12`
- OpenJDK `java -version`：通过，版本 `21.0.12`
- OpenJDK `javac -version`：通过，版本 `21.0.12`
- `brew doctor`：通过
- 登录 Shell：通过，`JAVA_HOME`、`java` 和 `javac` 均指向 Homebrew OpenJDK 21
- `make test`：通过，Java 使用本机 JDK 完成冒烟测试，未使用 Docker 回退

## 项目治理 DOC-002

- 验证时间：2026-07-26
- 代码解释规则存在性检查：通过
- 精确行号与绝对路径要求检查：通过
- `AGENTS.md`、`doc/record.md` Markdown 代码围栏检查：通过
- `git diff --check`：通过
- 业务测试：不适用（仅修改开发治理文档）
