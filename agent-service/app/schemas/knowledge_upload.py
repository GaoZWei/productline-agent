"""上传HTTP命令只携带业务元数据和并发快照，目标和文件名来自路由及文件。"""

from app.schemas.knowledge import KnowledgeSchema
from app.schemas.managed_knowledge import (
    ManagedKnowledgeMetadata,
    NonnegativeCounter,
    PositiveRevision,
)


class KnowledgeUploadHttpCommand(KnowledgeSchema):
    """不允许调用方提交发布状态、物理位置、哈希或确认快照。"""

    metadata: ManagedKnowledgeMetadata
    expected_row_version: NonnegativeCounter | None = None
    expected_revision_no: PositiveRevision | None = None


class KnowledgeUploadError(KnowledgeSchema):
    """上传失败统一使用安全错误码及固定文案，不返回原始输入。"""

    trace_id: str
    code: str
    message: str
