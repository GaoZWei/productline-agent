"""人工确认操作日志的异步持久化访问。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operation_log import OperationLogRecord


class OperationLogRepository:
    """只提供一次创建和按Approval读取; 日志创建后不可修改。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: OperationLogRecord) -> OperationLogRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_approval(self, approval_id: str) -> OperationLogRecord | None:
        result = await self._session.scalars(
            select(OperationLogRecord).where(OperationLogRecord.approval_id == approval_id)
        )
        return result.one_or_none()
