"""统一评测套件注册、选择和顺序执行入口。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import BaseModel
# 名称校验
_SUITE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# 统一执行函数类型 不接受运行时参数、异步函数、返回可序列化的Pydantic报告
EvaluationExecutor = Callable[[], Awaitable[BaseModel]]

# 配置错误 表示运行前配置不合法
class EvalRunnerConfigurationError(ValueError):
    """评测套件注册或选择不满足稳定执行契约。"""

# 执行错误 表示Suite内部执行失败
class EvalSuiteExecutionError(RuntimeError):
    """单个评测套件执行失败, 并只对外暴露套件身份。"""

    def __init__(self, suite_name: str) -> None:
        super().__init__(f"evaluation suite failed: {suite_name}")
        self.suite_name = suite_name

# 返回结果错误 表示Suite返回的报告不符合预期
class EvalSuiteResultError(TypeError):
    """评测套件没有返回可供后续统一序列化的Pydantic报告。"""

    def __init__(self, suite_name: str) -> None:
        super().__init__(f"evaluation suite returned an invalid report: {suite_name}")
        self.suite_name = suite_name

# 一个评测任务的定义
@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    """一个命名评测套件及其无参数异步执行入口。"""

    name: str
    execute: EvaluationExecutor

    def __post_init__(self) -> None:
        """在进入Runner前拒绝不稳定名称和不可调用入口。"""

        if not isinstance(self.name, str) or _SUITE_NAME_PATTERN.fullmatch(self.name) is None:
            raise EvalRunnerConfigurationError(
                "evaluation suite name must match ^[a-z][a-z0-9_]{0,63}$"
            )
        if not callable(self.execute):
            raise EvalRunnerConfigurationError("evaluation suite executor must be callable")


class EvalRunner:
    """按确定顺序运行已注册套件, 供后续统一报告层复用。"""

    def __init__(self, suites: Sequence[EvaluationSuite]) -> None:
        # 把输入转成元组, 确保不可变性
        fixed_suites = tuple(suites)
        # 进行检查
        if not fixed_suites:
            raise EvalRunnerConfigurationError("at least one evaluation suite is required")

        names = tuple(suite.name for suite in fixed_suites)
        if len(set(names)) != len(names):
            raise EvalRunnerConfigurationError("evaluation suite names must be unique")
        # 保存两个结构 一个按注册顺序, 一个按名称索引
        self._suites = fixed_suites
        self._suite_by_name = {suite.name: suite for suite in fixed_suites}
    # suite_names属性 表示固定注册顺序, 供CLI或报告层展示可用套件
    @property
    def suite_names(self) -> tuple[str, ...]:
        """返回固定注册顺序, 供CLI或报告层展示可用套件。"""

        return tuple(suite.name for suite in self._suites)
    # 核心执行逻辑
    async def run(
        self,
        selected_suites: Sequence[str] | None = None,
    ) -> Mapping[str, BaseModel]:
        """按注册或显式选择顺序执行, 并返回只读的套件报告映射。"""
        # 第一步：解析要运行的Suite列表
        suites = self._select_suites(selected_suites)
        # 第二步：创建本次结果容器
        reports: dict[str, BaseModel] = {}
        # 第三步：串行执行每个Suite
        for suite in suites:
            try:
                report = await suite.execute()
            # 第四步：包装执行异常
            except Exception as error:
                raise EvalSuiteExecutionError(suite.name) from error
            # 第五步：校验报告类型
            if not isinstance(report, BaseModel):
                raise EvalSuiteResultError(suite.name)
            # 每完成一个Suite，就以Suite名称保存结果
            reports[suite.name] = report
        # 第六步：返回只读映射
        return MappingProxyType(reports)
    # 在任何Suite运行前检查
    def _select_suites(
        self,
        selected_suites: Sequence[str] | None,
    ) -> tuple[EvaluationSuite, ...]:
        """在执行前完成选择校验, 避免部分评测后才发现配置错误。"""

        if selected_suites is None:
            return self._suites

        names = tuple(selected_suites)
        if not names:
            raise EvalRunnerConfigurationError("selected evaluation suites must be nonempty")
        if len(set(names)) != len(names):
            raise EvalRunnerConfigurationError("selected evaluation suite names must be unique")

        unknown_names = tuple(name for name in names if name not in self._suite_by_name)
        if unknown_names:
            raise EvalRunnerConfigurationError(
                f"unknown evaluation suite: {unknown_names[0]}"
            )
        return tuple(self._suite_by_name[name] for name in names)
