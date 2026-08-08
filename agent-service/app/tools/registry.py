"""按稳定名称保存 Tool 实例的进程内注册表。"""

from typing import Any

from app.tools.base import BaseTool


class DuplicateToolRegistrationError(ValueError):
    """表示两个 Tool 使用了同一个注册名称。"""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"tool is already registered: {name}")


class ToolNotRegisteredError(LookupError):
    """表示调用方请求了尚未注册的 Tool 名称。"""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"tool is not registered: {name}")


# 注册表只负责按名称保存, 不理解每个 Tool 的输入输出类型。
# 具体类型由 Tool 自己的 input_model 和 output_model 保证。
class ToolRegistry:
    """提供确定性的 Tool 注册、查找和名称枚举能力。"""
    # init其实就是初始化state数据结构
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool[Any, Any]] = {}

    def register(self, tool: BaseTool[Any, Any]) -> None:
        """注册一个 Tool 并拒绝静默覆盖已有名称。"""

        if tool.name in self._tools:
            raise DuplicateToolRegistrationError(tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool[Any, Any]:
        """按稳定名称返回 Tool。未知名称使用独立注册表异常。"""

        try:
            return self._tools[name]
        except KeyError as exception:
            raise ToolNotRegisteredError(name) from exception

    @property
    def names(self) -> tuple[str, ...]:
        """返回排序后的不可变名称快照以保证测试结果稳定。"""

        return tuple(sorted(self._tools))

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
