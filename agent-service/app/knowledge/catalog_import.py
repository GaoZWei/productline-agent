"""首批纳管确认与确定性管理身份，复用旧引用而不伪造模型生成。"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from app.knowledge.import_preflight import ImportFiles
from app.knowledge.publication import publication_generation_hash
from app.schemas.knowledge_import import KnowledgeImportCommand, KnowledgeImportPreflight
from app.schemas.knowledge_publication import KnowledgePublicationIndexIdentity
from app.schemas.managed_knowledge import ManagedKnowledgeRevisionSnapshot
from app.schemas.managed_knowledge_processing import ManagedKnowledgeConfirmation


def _digest(payload: object) -> str:
    """规范序列化只用于内容绑定，不作为签名或授权票据。"""

    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def import_digest(report: KnowledgeImportPreflight) -> str:
    """绑定源完整指纹、实际用户/范围、目标计数及索引配置。"""

    return _digest(
        {
            "contract": "knowledge-catalog-import-v1",
            "actor": report.checked_by,
            "scope": report.permission_scope.value,
            "catalog": report.source_catalog_hash,
            "source": report.source_fingerprint,
            "release": report.library_release_revision,
            "index": report.index.model_dump(mode="json"),
        }
    )


def import_request_hash(command: KnowledgeImportCommand) -> str:
    """成功重放按原请求核对，不再依赖已改变的源文件或当前模型配置。"""

    return _digest(
        {"contract": "knowledge-catalog-import-request-v1", **command.model_dump(mode="json")}
    )


def import_keys(command: KnowledgeImportCommand) -> tuple[str, ...]:
    """派生16个有序键，UPLOAD/PUBLISH各自的唯一约束共同保存整批审计。"""

    batch = hashlib.sha256(command.idempotency_key.encode()).hexdigest()
    return tuple(f"import:{batch}:{number:02d}" for number in range(16))


@dataclass(frozen=True, slots=True)
class CatalogImportVersion:
    """完成确认后才生成的本次版本及不可变原件快照。"""

    source_id: str
    document_id: str
    version_id: str
    generation_id: str
    upload_operation_id: str
    publish_operation_id: str
    parse_task_id: str
    index_task_id: str
    operation_key: str
    snapshot: ManagedKnowledgeRevisionSnapshot
    raw: bytes
    lifecycle: str
    replaced_by: str | None
    generation_hash: str

    def confirmation(self, actor: str, action: str) -> ManagedKnowledgeConfirmation:
        """每个版本保留真实人工动作，不把旧库indexed_at当作管理发布时间。"""

        return ManagedKnowledgeConfirmation.model_validate(
            {
                "actor_id": actor,
                "action": action,
                "document_id": self.document_id,
                "version_id": self.version_id,
                "revision_no": 1,
                "raw_hash": self.snapshot.raw_hash,
                "normalized_hash": self.snapshot.normalized_hash,
                "metadata_hash": self.snapshot.metadata_digest(),
                "expected_row_version": 0,
                "generation_id": self.generation_id if action == "PUBLISH" else None,
            }
        )


def import_plan(
    files: ImportFiles,
    command: KnowledgeImportCommand,
    *,
    actor: str,
    index: KnowledgePublicationIndexIdentity,
) -> tuple[CatalogImportVersion, ...]:
    """同一已确认请求重试复用原件key，不覆盖失败留下的其他请求原件。"""

    request_hash = import_request_hash(command)

    def identifier(prefix: str, target: str) -> str:
        """派生身份只影响新管理数据，固定规范及引用ID原样保留。"""
        return (
            prefix
            + "-"
            + uuid5(
                NAMESPACE_URL, f"urn:knowledge-import:v1:{actor}:{request_hash}:{prefix}:{target}"
            ).hex.upper()
        )

    entries: list[CatalogImportVersion] = []
    for source, key in zip(
        sorted(files.files, key=lambda item: item.metadata.document_id),
        import_keys(command),
        strict=True,
    ):
        metadata = source.metadata
        source_id = metadata.document_id
        document_id = identifier("DOC", metadata.replaced_by or source_id)
        version_id = identifier("VER", source_id)
        suffix = PurePosixPath(metadata.file_path).suffix.lower().removeprefix(".")
        snapshot = ManagedKnowledgeRevisionSnapshot.model_validate(
            {
                **metadata.model_dump(
                    exclude={"document_id", "file_path", "lifecycle", "replaced_by"}
                ),
                "version_id": version_id,
                "revision_no": 1,
                "original_key": f"versions/{version_id}/revisions/1/original.{suffix}",
                "original_filename": PurePosixPath(metadata.file_path).name,
                "file_format": "MD" if suffix == "md" else "TXT",
                "byte_size": len(source.raw),
                "raw_hash": hashlib.sha256(source.raw).hexdigest(),
                "body": source.parsed.body,
                "normalized_hash": source.parsed.normalized_hash,
                "created_by": actor,
                "change_summary": "首批演示规范纳管，保留旧规范引用与索引",
            }
        )
        confirmation = ManagedKnowledgeConfirmation(
            actor_id=actor,
            action="PUBLISH",
            document_id=document_id,
            version_id=version_id,
            revision_no=1,
            raw_hash=snapshot.raw_hash,
            normalized_hash=snapshot.normalized_hash,
            metadata_hash=snapshot.metadata_digest(),
            expected_row_version=0,
        )
        entries.append(
            CatalogImportVersion(
                source_id,
                document_id,
                version_id,
                identifier("GEN", source_id),
                identifier("OP", source_id + ":upload"),
                identifier("OP", source_id + ":publish"),
                identifier("TASK", source_id + ":parse"),
                identifier("TASK", source_id + ":index"),
                key,
                snapshot,
                source.raw,
                metadata.lifecycle.value,
                metadata.replaced_by,
                publication_generation_hash(confirmation, source_id, index),
            )
        )
    return tuple(entries)
