"""知识库全量入库CLI, 只有显式执行时才访问Embedding服务。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path

from pydantic import ValidationError

from app.database import Database
from app.knowledge import (
    DocumentLoadError,
    DuplicateDocumentError,
    EmbeddingBatchGenerator,
    EmbeddingConfig,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingProvider,
)
from app.repositories import KnowledgeIndexRepository, KnowledgeIndexValidationError
from app.schemas.knowledge_index import KnowledgeIngestionSummary
from app.services.knowledge_ingestion import (
    DEFAULT_KNOWLEDGE_ROOT,
    KnowledgeCatalogLoadError,
    KnowledgeIngestionService,
)
from app.settings import Settings, get_settings

_LOGGER = logging.getLogger("agent-service.knowledge-ingest")


class KnowledgeIngestionExitCode(IntEnum):
    """脚本调用方可稳定判断的退出码。"""

    SUCCESS = 0
    INPUT_OR_CONFIGURATION_ERROR = 2
    EMBEDDING_ERROR = 3
    PERSISTENCE_ERROR = 4

# 入库命令入口
# 组装完整运行环境
async def run_ingestion(
    settings: Settings,
    *,
    knowledge_root: Path,
    catalog_path: Path | None,
) -> KnowledgeIngestionSummary:
    """创建仅本次命令使用的Provider和数据库连接并原子提交索引。"""

    try:  # 从配置创建 EmbeddingConfig
        embedding_config = EmbeddingConfig.from_settings(settings)
    except ValueError as error:
        raise KnowledgeIngestionConfigurationError(
            "embedding configuration is incomplete"
        ) from error

    try:
        database = Database(settings.database_url)
    except ValueError as error:
        raise KnowledgeIngestionConfigurationError("database configuration is invalid") from error
    # 创建 OpenAI-compatible Embedding Provider
    provider = OpenAICompatibleEmbeddingProvider(embedding_config)
    try:
        # 创建批量向量生成器
        generator = EmbeddingBatchGenerator(embedding_config, provider)
        # 建立数据库 Session 和事务
        async with database.session() as session, session.begin():
            # 调用知识入库服务
            return await KnowledgeIngestionService(
                repository=KnowledgeIndexRepository(session),
                embedding_generator=generator,
            ).ingest_catalog(knowledge_root, catalog_path)
    finally:
        try:
            await provider.aclose()
        finally:
            await database.dispose()


class KnowledgeIngestionConfigurationError(ValueError):
    """CLI启动所需的Embedding配置不完整。"""


def main(argv: Sequence[str] | None = None) -> int:
    """执行全量入库并只输出不含密钥、正文或向量的JSON结果。"""

    parser = argparse.ArgumentParser(description="全量重建知识库Embedding索引")
    parser.add_argument(
        "--knowledge-root",
        type=Path,
        default=DEFAULT_KNOWLEDGE_ROOT,
        help="知识库根目录, 默认使用仓库内knowledge-base",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="目录JSON路径, 默认使用知识库根目录下catalog.json",
    )
    arguments = parser.parse_args(argv)

    try:
        summary = asyncio.run(
            run_ingestion(
                get_settings(),
                knowledge_root=arguments.knowledge_root,
                catalog_path=arguments.catalog,
            )
        )
    except (
        KnowledgeIngestionConfigurationError,
        ValidationError,
        KnowledgeCatalogLoadError,
        DocumentLoadError,
        DuplicateDocumentError,
        KnowledgeIndexValidationError,
    ) as error:
        return _failure(
            KnowledgeIngestionExitCode.INPUT_OR_CONFIGURATION_ERROR,
            "KNOWLEDGE_INGESTION_INPUT_ERROR",
            error,
        )
    except EmbeddingProviderError as error:
        return _failure(
            KnowledgeIngestionExitCode.EMBEDDING_ERROR,
            error.code.value,
            error,
        )
    except ValueError as error:
        return _failure(
            KnowledgeIngestionExitCode.EMBEDDING_ERROR,
            "EMBEDDING_OUTPUT_VALIDATION_ERROR",
            error,
        )
    except Exception as error:
        return _failure(
            KnowledgeIngestionExitCode.PERSISTENCE_ERROR,
            "KNOWLEDGE_INGESTION_PERSISTENCE_ERROR",
            error,
        )

    print(
        json.dumps(
            {"ok": True, **summary.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return KnowledgeIngestionExitCode.SUCCESS


def _failure(
    exit_code: KnowledgeIngestionExitCode,
    error_code: str,
    error: Exception,
) -> int:
    """记录异常类型并向命令调用方返回不泄露内部详情的稳定错误。"""

    _LOGGER.error(
        "knowledge_ingestion_failed",
        extra={"error_code": error_code, "error_type": type(error).__name__},
    )
    print(json.dumps({"ok": False, "error_code": error_code}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
