"""原件边界、字节完整性、取消清理及单份解析的离线验收。"""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.knowledge.managed_parsing import parse_managed_revision
from app.knowledge.storage import MAX_ORIGINAL_BYTES, KnowledgeOriginalStorage
from app.schemas.knowledge_management import KnowledgeManagementError, KnowledgeUploadCommand
from app.settings import Settings
from tests.knowledge.managed_knowledge_fixtures import VERSION_ID, byte_chunks, revision_payload


def key(revision: int = 1) -> str:
    """固定独立管理身份，不复用catalog。"""

    return f"versions/{VERSION_ID}/revisions/{revision}/original.md"


@pytest.mark.unit
async def test_original_keeps_raw_bytes_and_never_overwrites_committed_file(tmp_path: Path) -> None:
    store = KnowledgeOriginalStorage(tmp_path / "originals")
    assert not store.root.exists()
    raw = b"\xef\xbb\xbf# test\r\nbody\r\n"
    staged = await store.stage(byte_chunks(raw[:4], raw[4:]), "test.MD")
    store.commit(staged, key())
    store.discard(staged)
    assert store.read(key(), hashlib.sha256(raw).hexdigest(), len(raw)) == raw
    # 数据库失败留下的同字节原件可受控复用，不覆盖已有内容。
    retry = await store.stage(byte_chunks(raw), "test.md")
    store.commit(retry, key())
    store.discard(retry)
    different = await store.stage(byte_chunks(b"# other"), "other.md")
    with pytest.raises(KnowledgeManagementError, match="ORIGINAL_CONFLICT"):
        store.commit(different, key())
    store.discard(different)
    assert store.read(key(), hashlib.sha256(raw).hexdigest(), len(raw)) == raw
    assert list((store.root / "_temporary").iterdir()) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "filename", "code"),
    [
        (b"", "test.md", "EMPTY_DOCUMENT"),
        (b" \r\n", "test.txt", "EMPTY_DOCUMENT"),
        (b"\xff", "test.txt", "INVALID_ENCODING"),
        (b"text\x00binary", "test.txt", "INVALID_TEXT_CONTENT"),
        (b"valid", "test.pdf", "UNSUPPORTED_FORMAT"),
        (b"valid", "../test.md", "INVALID_FILENAME"),
        (b"valid", "unsafe\nname.md", "INVALID_FILENAME"),
        (b"valid", "folder\\test.md", "INVALID_FILENAME"),
    ],
)
async def test_original_rejects_bad_upload_and_cleans_temporary_files(
    tmp_path: Path,
    raw: bytes,
    filename: str,
    code: str,
) -> None:
    store = KnowledgeOriginalStorage(tmp_path / "originals")
    with pytest.raises(KnowledgeManagementError, match=code):
        await store.stage(byte_chunks(raw), filename)
    assert list(store.root.rglob("*.part")) == []


@pytest.mark.unit
async def test_original_enforces_limit_across_chunks_and_cleans_cancellation(
    tmp_path: Path,
) -> None:
    store = KnowledgeOriginalStorage(tmp_path / "originals")
    with pytest.raises(KnowledgeManagementError, match="FILE_TOO_LARGE"):
        await store.stage(byte_chunks(b"a" * MAX_ORIGINAL_BYTES, b"b"), "test.txt")

    async def cancelled() -> AsyncIterator[bytes]:
        """上传流中断应清理临时文件，但保留取消语义。"""
        yield b"started"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await store.stage(cancelled(), "test.txt")
    assert list(store.root.rglob("*.part")) == []


@pytest.mark.unit
async def test_original_rejects_traversal_symlinks_tampering_and_missing_files(
    tmp_path: Path,
) -> None:
    store = KnowledgeOriginalStorage(tmp_path / "originals")
    outside = tmp_path / "outside"
    outside.mkdir()
    staged = await store.stage(byte_chunks(b"# test"), "test.md")
    for target in ("../outside/test.md", "/tmp/test.md", key().replace("/1/", "/../")):
        with pytest.raises(KnowledgeManagementError, match="INVALID_STORAGE_PATH"):
            store.commit(staged, target)
    with pytest.raises(KnowledgeManagementError, match="INVALID_STORAGE_PATH"):
        store.commit(replace(staged, name="../outside"), key())
    (store.root / "versions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(KnowledgeManagementError):
        store.commit(staged, key())
    assert list(outside.iterdir()) == []
    (store.root / "versions").unlink()
    store.commit(staged, key())
    store.discard(staged)
    file = store.root / key()
    file.write_bytes(b"corrupt")
    with pytest.raises(KnowledgeManagementError, match="ORIGINAL_INTEGRITY_ERROR"):
        store.read(key(), staged.raw_hash, staged.byte_size)
    file.unlink()
    file.symlink_to(outside / "hidden.md")
    with pytest.raises(KnowledgeManagementError):
        store.read(key(), staged.raw_hash, staged.byte_size)
    file.unlink()
    with pytest.raises(KnowledgeManagementError, match="ORIGINAL_NOT_FOUND"):
        store.read(key(), staged.raw_hash, staged.byte_size)


@pytest.mark.unit
def test_managed_parser_preserves_normalized_body_and_stable_chunks() -> None:
    raw = "\ufeff# 测试规范\r\n\r\n## 要求\r\n  正文\r\n".encode()
    parsed = parse_managed_revision(
        raw, citation_document_id=VERSION_ID, title="测试规范", file_format="MD"
    )
    normalized = raw.decode().removeprefix("\ufeff").replace("\r\n", "\n")
    assert parsed.body == normalized
    assert parsed.normalized_hash == hashlib.sha256(normalized.encode()).hexdigest()
    again = parse_managed_revision(
        normalized.encode(), citation_document_id=VERSION_ID, title="测试规范", file_format="MD"
    )
    assert parsed.chunks == again.chunks
    text = parse_managed_revision(
        b" plain body \r\n", citation_document_id=VERSION_ID, title="TXT title", file_format="TXT"
    )
    assert text.body == " plain body \n"
    assert text.chunks[0].section_path == ("TXT title",)
    with pytest.raises(ValueError, match="title"):
        parse_managed_revision(
            raw, citation_document_id=VERSION_ID, title="wrong title", file_format="MD"
        )


@pytest.mark.unit
def test_storage_configuration_is_absolute_and_upload_schema_rejects_untrusted_fields() -> None:
    root = Settings(_env_file=None).knowledge_storage_root
    assert root.is_absolute() and root.parts[-2:] == (".local", "knowledge-storage")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, knowledge_storage_root=Path("relative"))
    metadata = {
        name: revision_payload()[name]
        for name in (
            "title",
            "document_type",
            "specification_version",
            "effective_date",
            "permission_scope",
            "change_summary",
        )
    }
    payload = {"filename": "test.md", "metadata": metadata, "idempotency_key": "key-1"}
    assert KnowledgeUploadCommand.model_validate(payload).version_id is None
    for update in (
        {"raw_hash": "a" * 64},
        {"publication_state": "PUBLISHED"},
        {"filename": "../test.md"},
        {"version_id": VERSION_ID},
    ):
        with pytest.raises(ValidationError):
            KnowledgeUploadCommand.model_validate({**payload, **update})
