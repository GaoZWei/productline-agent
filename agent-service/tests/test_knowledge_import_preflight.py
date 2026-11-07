"""首批纳管只读检查：授权、源文件安全、完整证据与过期快照边界。"""

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.errors import ToolException
from app.knowledge.import_preflight import (
    ImportFiles,
    capture_import_files,
    file_fingerprint,
    validate_import_source,
)
from app.knowledge.pipeline import DocumentProcessingPipeline
from app.repositories.knowledge_import import KnowledgeImportPreflightRepository
from app.schemas.knowledge import DocumentCatalog
from app.schemas.knowledge_management import KnowledgeManagementError
from app.services.knowledge_import import KnowledgeImportPreflightService
from app.services.knowledge_ingestion import DEFAULT_KNOWLEDGE_ROOT
from tests.knowledge.import_preflight_fixtures import INDEX, source_snapshot
from tests.test_knowledge_publication import IDENTITY, PublicationHarness
from tests.test_knowledge_publication import publication as publication


@pytest.fixture
def files() -> ImportFiles:
    """只读真实固定语料，失败场景仅修改临时副本。"""

    return capture_import_files(DEFAULT_KNOWLEDGE_ROOT)


def test_preflight_preserves_existing_chunk_identity_and_groups_history(files: ImportFiles) -> None:
    catalog = DocumentCatalog.model_validate_json(
        (DEFAULT_KNOWLEDGE_ROOT / "catalog.json").read_bytes()
    )
    existing = DocumentProcessingPipeline().process_catalog(DEFAULT_KNOWLEDGE_ROOT, catalog)
    assert [item.parsed.chunks for item in files.files] == [item.chunks for item in existing]
    report = validate_import_source(
        files,
        source_snapshot(files),
        actor="reviewer",
        scope="INTERNAL_REVIEWER",
        expected_index=INDEX,
    )
    assert report.version_count == 16 and report.chunk_count == 80 and report.is_demo
    assert len({item.logical_document_key for item in report.versions}) == 14
    for item in report.versions:
        if item.lifecycle == "HISTORICAL":
            assert item.logical_document_key == item.replaced_by
            assert item.logical_document_key in {
                entry.source_document_id for entry in report.versions
            }
    assert sum(item.lifecycle == "HISTORICAL" for item in report.versions) == 2
    payload = report.model_dump_json()
    assert "embedding" not in payload and '"body"' not in payload
    assert str(DEFAULT_KNOWLEDGE_ROOT) not in payload
    assert report == validate_import_source(
        files,
        source_snapshot(files),
        actor="reviewer",
        scope="INTERNAL_REVIEWER",
        expected_index=INDEX,
    )


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("source_mode", "IMPORT_SOURCE_MODE_CONFLICT"),
        ("source_catalog_hash", "IMPORT_SOURCE_CONFLICT"),
        ("target_conflict", "IMPORT_TARGET_CONFLICT"),
        ("document_count", "IMPORT_LEGACY_INCOMPLETE"),
        ("chunk_count", "IMPORT_LEGACY_CHUNKS_INVALID"),
    ],
)
def test_preflight_rejects_incomplete_or_already_used_target(
    files: ImportFiles, field: str, code: str
) -> None:
    original = source_snapshot(files)
    stored = {
        "source_mode": replace(original, source_mode="MANAGED"),
        "source_catalog_hash": replace(original, source_catalog_hash="f" * 64),
        "target_conflict": replace(original, target_conflict=True),
        "document_count": replace(original, document_count=17),
        "chunk_count": replace(original, chunk_count=79),
    }[field]
    with pytest.raises(KnowledgeManagementError, match=code):
        validate_import_source(
            files, stored, actor="reviewer", scope="INTERNAL_REVIEWER", expected_index=INDEX
        )


def test_preflight_cannot_treat_existing_import_as_first_import(files: ImportFiles) -> None:
    with pytest.raises(KnowledgeManagementError, match="IMPORT_ALREADY_PRESENT"):
        validate_import_source(
            files,
            replace(source_snapshot(files), source_catalog_hash=files.catalog_hash),
            actor="reviewer",
            scope="INTERNAL_REVIEWER",
            expected_index=INDEX,
        )


@pytest.mark.parametrize(
    "kind",
    [
        "metadata",
        "hash",
        "index",
        "missing-document",
        "missing-chunk",
        "section",
        "body",
        "tokens",
        "search",
        "vector-zero",
        "vector-nan",
        "vector-inf",
        "vector-large",
        "vector-short",
    ],
)
def test_preflight_checks_full_legacy_evidence(files: ImportFiles, kind: str) -> None:
    stored = source_snapshot(files)
    first = stored.documents[0]
    chunk = stored.chunks[0]
    code = "IMPORT_LEGACY_CHUNKS_INVALID"
    if kind == "metadata":
        stored = replace(
            stored,
            documents=(
                replace(first, metadata=first.metadata.model_copy(update={"title": "changed"})),
                *stored.documents[1:],
            ),
        )
        code = "IMPORT_LEGACY_DOCUMENT_MISMATCH"
    elif kind == "hash":
        stored = replace(
            stored, documents=(replace(first, content_hash="a" * 64), *stored.documents[1:])
        )
        code = "IMPORT_LEGACY_DOCUMENT_MISMATCH"
    elif kind == "index":
        stored = replace(
            stored,
            documents=(
                replace(first, index=INDEX.model_copy(update={"model": "other"})),
                *stored.documents[1:],
            ),
        )
        code = "IMPORT_INDEX_IDENTITY_MISMATCH"
    elif kind == "missing-document":
        stored = replace(stored, documents=stored.documents[1:])
        code = "IMPORT_LEGACY_INCOMPLETE"
    elif kind == "missing-chunk":
        stored = replace(stored, chunks=stored.chunks[1:])
    else:
        changed = {
            "section": replace(chunk, section_path=("wrong",)),
            "body": replace(chunk, content="changed"),
            "tokens": replace(chunk, token_count=chunk.token_count + 1),
            "search": replace(chunk, search_document="changed"),
            "vector-zero": replace(chunk, embedding=(0.0,) * 1536),
            "vector-nan": replace(chunk, embedding=(float("nan"),) + (0.0,) * 1535),
            "vector-inf": replace(chunk, embedding=(float("inf"),) + (0.0,) * 1535),
            "vector-large": replace(chunk, embedding=(1e39,) + (0.0,) * 1535),
            "vector-short": replace(chunk, embedding=(1.0,)),
        }[kind]
        stored = replace(stored, chunks=(changed, *stored.chunks[1:]))
        if kind.startswith("vector"):
            code = "IMPORT_LEGACY_VECTOR_INVALID"
    with pytest.raises(KnowledgeManagementError, match=code):
        validate_import_source(
            files, stored, actor="reviewer", scope="INTERNAL_REVIEWER", expected_index=INDEX
        )


def test_fingerprint_binds_original_bytes_and_every_vector(files: ImportFiles) -> None:
    stored = source_snapshot(files)

    def fingerprint(source: ImportFiles, vector_changed: bool = False) -> str:
        """保持分块正文相同，分别改变原始字节和一个已存向量。"""
        snapshot = stored
        if vector_changed:
            snapshot = replace(
                stored,
                chunks=(
                    replace(stored.chunks[0], embedding=(2.5,) + (0.0,) * 1535),
                    *stored.chunks[1:],
                ),
            )
        return validate_import_source(
            source, snapshot, actor="reviewer", scope="INTERNAL_REVIEWER", expected_index=INDEX
        ).source_fingerprint

    changed = replace(
        files,
        files=(replace(files.files[0], raw=b"\xef\xbb\xbf" + files.files[0].raw), *files.files[1:]),
    )
    assert len({fingerprint(files), fingerprint(changed), fingerprint(files, True)}) == 3
    assert file_fingerprint(files) != file_fingerprint(changed)


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "encoding",
        "missing",
        "symlink",
        "directory-symlink",
        "traversal",
        "count",
        "duplicate-version",
        "oversize",
        "special",
        "catalog-symlink",
        "root-symlink",
        "nul",
    ],
)
def test_capture_rejects_bad_source_without_following_links(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "source"
    shutil.copytree(DEFAULT_KNOWLEDGE_ROOT, root)
    catalog_path = root / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    path = root / catalog["documents"][0]["file_path"]
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "encoding":
        path.write_bytes(b"\xff\xfe")
    elif kind == "missing":
        path.unlink()
    elif kind == "symlink":
        path.unlink()
        path.symlink_to(DEFAULT_KNOWLEDGE_ROOT / catalog["documents"][0]["file_path"])
    elif kind == "directory-symlink":
        shutil.rmtree(root / "active")
        (root / "active").symlink_to(DEFAULT_KNOWLEDGE_ROOT / "active", target_is_directory=True)
    elif kind == "oversize":
        with path.open("wb") as original:
            original.truncate(10485761)
    elif kind == "special":
        path.unlink()
        os.mkfifo(path)
    elif kind == "catalog-symlink":
        catalog_path.unlink()
        catalog_path.symlink_to(DEFAULT_KNOWLEDGE_ROOT / "catalog.json")
    elif kind == "root-symlink":
        shutil.rmtree(root)
        root.symlink_to(DEFAULT_KNOWLEDGE_ROOT, target_is_directory=True)
    elif kind == "nul":
        path.write_bytes(path.read_bytes() + b"\x00")
    else:
        if kind == "traversal":
            catalog["documents"][0]["file_path"] = "../outside.md"
        elif kind == "count":
            catalog["documents"].pop()
        else:
            historical = next(
                item for item in catalog["documents"] if item["lifecycle"] == "HISTORICAL"
            )
            active = next(
                item
                for item in catalog["documents"]
                if item["document_id"] == historical["replaced_by"]
            )
            historical["specification_version"] = active["specification_version"]
        catalog_path.write_text(json.dumps(catalog))
    with pytest.raises(KnowledgeManagementError):
        capture_import_files(root)


async def test_service_reauthorizes_both_actions_and_rechecks_files(
    publication: PublicationHarness, files: ImportFiles
) -> None:
    repository = Mock(spec=KnowledgeImportPreflightRepository)
    repository.read_source = AsyncMock(return_value=source_snapshot(files))
    service = KnowledgeImportPreflightService(
        repository, publication.service.authorizer, index_identity=INDEX
    )
    first = await service.check(identity=IDENTITY)
    assert first == await service.check(identity=IDENTITY)
    assert publication.actions == ["UPLOAD", "PUBLISH"] * 2
    assert repository.read_source.await_count == 2


@pytest.mark.parametrize("outcomes", [["DENIED"], ["SUCCESS", "DENIED"], ["INVALID_POLICY"]])
async def test_denial_precedes_files_and_sql(
    publication: PublicationHarness, tmp_path: Path, outcomes: list[str]
) -> None:
    publication.outcomes.extend(outcomes)
    repository = Mock(spec=KnowledgeImportPreflightRepository)
    repository.read_source = AsyncMock()
    service = KnowledgeImportPreflightService(
        repository,
        publication.service.authorizer,
        index_identity=INDEX,
        knowledge_root=tmp_path / "does-not-exist",
    )
    with pytest.raises(ToolException):
        await service.check(identity=IDENTITY)
    repository.read_source.assert_not_awaited()


async def test_changed_files_after_sql_are_rejected(
    publication: PublicationHarness, tmp_path: Path, files: ImportFiles
) -> None:
    root = tmp_path / "source"
    shutil.copytree(DEFAULT_KNOWLEDGE_ROOT, root)

    async def read_source(document_ids: tuple[str, ...], scope: str) -> object:
        """模拟快照读取期间另一个维护者改变原件。"""
        path = root / files.files[0].metadata.file_path
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        return source_snapshot(files)

    repository = Mock(spec=KnowledgeImportPreflightRepository)
    repository.read_source = AsyncMock(side_effect=read_source)
    service = KnowledgeImportPreflightService(
        repository, publication.service.authorizer, index_identity=INDEX, knowledge_root=root
    )
    with pytest.raises(KnowledgeManagementError, match="IMPORT_SOURCE_CHANGED"):
        await service.check(identity=IDENTITY)


async def test_sql_error_is_safe_without_fallback(publication: PublicationHarness) -> None:
    repository = Mock(spec=KnowledgeImportPreflightRepository)
    repository.read_source = AsyncMock(side_effect=SQLAlchemyError("secret URL"))
    service = KnowledgeImportPreflightService(
        repository, publication.service.authorizer, index_identity=INDEX
    )
    with pytest.raises(
        KnowledgeManagementError, match="KNOWLEDGE_PERSISTENCE_UNAVAILABLE"
    ) as caught:
        await service.check(identity=IDENTITY)
    assert "secret" not in str(caught.value)
