"""知识文档加载、确定性分块、重复检测和Embedding生成能力。"""

from app.knowledge.chunking import DocumentChunk, HeadingDocumentChunker
from app.knowledge.embeddings import (
    ChunkEmbedding,
    EmbeddingBatchGenerator,
    EmbeddingConfig,
    EmbeddingErrorCode,
    EmbeddingGeneration,
    EmbeddingIndexDescriptor,
    EmbeddingProvider,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingProvider,
    QueryEmbedding,
)
from app.knowledge.loaders import (
    DocumentFormat,
    DocumentLoader,
    DocumentLoaderRegistry,
    DocumentLoadError,
    LoadedDocument,
    MarkdownDocumentLoader,
    PlainTextDocumentLoader,
    UnsupportedDocumentFormatError,
    normalize_document_content,
)
from app.knowledge.pipeline import (
    DocumentProcessingPipeline,
    DuplicateDocumentDetector,
    DuplicateDocumentError,
    ProcessedDocument,
)
from app.knowledge.search import (
    KeywordQuery,
    KeywordQueryError,
    KeywordSearchHit,
    VectorSearchHit,
    build_search_document,
    preprocess_keyword_query,
)
from app.schemas.knowledge import EMBEDDING_DIMENSION

__all__ = [
    "EMBEDDING_DIMENSION",
    "ChunkEmbedding",
    "DocumentChunk",
    "DocumentFormat",
    "DocumentLoadError",
    "DocumentLoader",
    "DocumentLoaderRegistry",
    "DocumentProcessingPipeline",
    "DuplicateDocumentDetector",
    "DuplicateDocumentError",
    "EmbeddingBatchGenerator",
    "EmbeddingConfig",
    "EmbeddingErrorCode",
    "EmbeddingGeneration",
    "EmbeddingIndexDescriptor",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "HeadingDocumentChunker",
    "KeywordQuery",
    "KeywordQueryError",
    "KeywordSearchHit",
    "LoadedDocument",
    "MarkdownDocumentLoader",
    "OpenAICompatibleEmbeddingProvider",
    "PlainTextDocumentLoader",
    "ProcessedDocument",
    "QueryEmbedding",
    "UnsupportedDocumentFormatError",
    "VectorSearchHit",
    "build_search_document",
    "normalize_document_content",
    "preprocess_keyword_query",
]
