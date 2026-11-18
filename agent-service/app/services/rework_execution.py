"""M8写Tool与独立确认执行服务之间的受信接口。"""

from typing import Protocol

from app.schemas.rework_write_tools import ReworkExecutionSnapshot, ReworkWriteOutput


class ReworkExecutionStore(Protocol):
    """确认服务负责人工确认、归属、有效期、唯一执行权及提交前事实重校验。"""

    async def get_execution_snapshot(self, approval_id: str) -> ReworkExecutionSnapshot | None:
        """只读取服务端最终确认快照，不能由模型或Tool临时生成确认单。"""
        ...

    async def save_execution_result(
        self,
        expected: ReworkExecutionSnapshot,
        result: ReworkWriteOutput,
    ) -> bool:
        """按完整快照及EXECUTING执行CAS保存原结果，冲突必须返回False。

        实现须核对用户、Run、操作、键、资源、版本和材料未变，首次结果不可覆盖。
        原请求重放仅可接受相同业务回执并保留首次Trace，不能据此发放新的执行权。
        """
        ...

    async def begin_submission(self, expected: ReworkExecutionSnapshot) -> bool:
        """原子消费一次提交许可。重放、并发、到期或快照变化都不得再次发送Java。"""
        ...
