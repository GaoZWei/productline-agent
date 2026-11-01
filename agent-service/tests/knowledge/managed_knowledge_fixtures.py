"""独立管理资料测试的固定输入，不加载外部服务或演示语料。"""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

VERSION_ID = "VER-" + "1" * 32
DOCUMENT_ID = "DOC-" + "1" * 32
GENERATION_ID = "GEN-" + "1" * 32
OPERATION_ID = "OP-" + "1" * 32
TASK_ID = "TASK-" + "1" * 32
CREATED_AT = datetime(2026, 10, 31, tzinfo=UTC)


async def byte_chunks(*chunks: bytes) -> AsyncIterator[bytes]:
    """按确定性分段交付测试字节，不读取外部文件。"""

    for chunk in chunks:
        yield chunk


def revision_payload(**updates: object) -> dict[str, object]:
    """使用独立固定测试身份，不修改catalog或演示规范。"""

    payload: dict[str, object] = {
        "version_id": VERSION_ID,
        "revision_no": 1,
        "specification_version": "2.0",
        "original_key": f"versions/{VERSION_ID}/revisions/1/original.md",
        "original_filename": "测试规范.md",
        "file_format": "MD",
        "byte_size": 8,
        "raw_hash": "a" * 64,
        "title": "测试规范",
        "document_type": "QUALITY_SPEC",
        "effective_date": date(2030, 1, 1),
        "permission_scope": "INTERNAL_REVIEWER",
        "change_summary": "首次上传",
        "created_by": "test-user",
    }
    return {**payload, **updates}


def version_payload(**updates: object) -> dict[str, object]:
    """构造服务端内部版本记录。"""

    return {
        "version_id": VERSION_ID,
        "document_id": DOCUMENT_ID,
        "specification_version": "2.0",
        "citation_document_id": VERSION_ID,
        "source_kind": "UPLOAD",
        "created_by": "test-user",
        **updates,
    }


def generation_payload(**updates: object) -> dict[str, object]:
    """仅提供固定索引身份，不调用Embedding。"""

    return {
        "generation_id": GENERATION_ID,
        "version_id": VERSION_ID,
        "revision_no": 1,
        "embedding_provider": "openai_compatible",
        "embedding_model": "test-embedding",
        "embedding_dimension": 1536,
        "index_version": "test-index-v1",
        "chunking_version": "heading-v1",
        "input_hash": "a" * 64,
        "build_method": "GENERATED",
        "created_at": CREATED_AT,
        **updates,
    }


def confirmation_payload(**updates: object) -> dict[str, object]:
    """确认仅保存身份及哈希，不包含正文或凭据。"""

    return {
        "actor_id": "test-user",
        "action": "UPLOAD",
        "document_id": DOCUMENT_ID,
        "version_id": VERSION_ID,
        "revision_no": 1,
        "raw_hash": "a" * 64,
        "metadata_hash": "b" * 64,
        "expected_row_version": 0,
        **updates,
    }


def operation_payload(**updates: object) -> dict[str, object]:
    """操作以版本为目标，重试原任务由确认快照和任务关联保留。"""

    return {
        "operation_id": OPERATION_ID,
        "actor_id": "test-user",
        "action": "UPLOAD",
        "version_id": VERSION_ID,
        "revision_no": 1,
        "target_id": VERSION_ID,
        "idempotency_key": "test-upload-1",
        "input_hash": "c" * 64,
        "confirmation_snapshot": confirmation_payload(),
        "created_at": CREATED_AT,
        **updates,
    }


def task_payload(**updates: object) -> dict[str, object]:
    """初始解析任务未绑定批次，也不复用重试动作。"""

    return {
        "task_id": TASK_ID,
        "operation_id": OPERATION_ID,
        "operation_action": "UPLOAD",
        "version_id": VERSION_ID,
        "revision_no": 1,
        "task_type": "PARSE",
        "owner_id": "worker-test-1",
        "trace_id": "trace-test-1",
        "created_at": CREATED_AT,
        **updates,
    }


def chunk_payload(**updates: object) -> dict[str, object]:
    """确定性分块样本保留首尾空白和完整维度。"""

    content = " 测试规范正文\n"
    return {
        "generation_id": GENERATION_ID,
        "chunk_id": "KCH-TEST-001",
        "chunk_index": 0,
        "section_path": ("测试规范", "适用范围"),
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "token_count": 6,
        "search_document": "测试 规范 正文",
        "embedding": (1.0,) + (0.0,) * 1535,
        **updates,
    }
