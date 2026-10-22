"""知识检索共享的中文预处理和稳定结果契约。"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

_MAX_QUERY_CHARACTERS = 2000
_MAX_QUERY_TERMS = 64
_SEARCH_TOKEN_PATTERN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]+|[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*"
)
_CJK_PATTERN = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff]+$")
_LOGGER = logging.getLogger("agent-service.keyword-query")


class KeywordQueryError(ValueError):
    """关键词查询为空、超出规范问答上限或无法产生安全检索词元。"""


@dataclass(frozen=True, slots=True)
class KeywordQuery:
    """交给PostgreSQL plainto_tsquery的受控词元。"""

    terms: tuple[str, ...]
    search_text: str


@dataclass(frozen=True, slots=True)
class KeywordSearchHit:
    """一个带PostgreSQL全文相关度的知识分块。"""

    chunk_id: str  # chunk_id 不能表示顺序, 用于唯一标识一个Chunk
    document_id: str
    document_name: str
    document_version: str
    chunk_index: int  # chunk_index: 当前文档内顺序
    section_path: tuple[str, ...]
    content: str
    content_hash: str
    keyword_score: float


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    """一个带余弦相似度的知识分块。"""

    chunk_id: str
    document_id: str
    document_name: str
    document_version: str
    chunk_index: int
    section_path: tuple[str, ...]
    content: str
    content_hash: str
    vector_score: float


# 中文预处理
def preprocess_keyword_query(query: str) -> KeywordQuery:
    """将中文连续文本转成双字词元, 并保留安全的英文与业务标识。"""
    # NFKC用于统一视觉相近但Unicode编码不同的字符, 例如全角GF-2和半角GF-2
    normalized = unicodedata.normalize("NFKC", query).strip()
    # 与规范问答入口保持相同上限，不能因模型生成较长查询而在内部突然拒绝。
    if not normalized or len(normalized) > _MAX_QUERY_CHARACTERS:
        raise KeywordQueryError("keyword query must contain 1 to 2000 characters")

    # 提取所有允许的词元
    terms: list[str] = []
    # _SEARCH_TOKEN_PATTERN是对应正则表达式的模式
    for match in _SEARCH_TOKEN_PATTERN.finditer(normalized):
        token = match.group(0)
        if _CJK_PATTERN.fullmatch(token):
            if len(token) < 2:
                continue
            # 中文生成双字词元
            terms.extend(token[index : index + 2] for index in range(len(token) - 1))
        else:
            terms.append(token.lower())

    # 去重且保持顺序
    unique_terms = tuple(dict.fromkeys(terms))
    if not unique_terms:
        raise KeywordQueryError("keyword query produced no usable terms")
    if len(unique_terms) > _MAX_QUERY_TERMS:
        _LOGGER.info(
            "keyword_query_bounded;query_characters=%d;input_terms=%d;selected_terms=%d",
            len(normalized),
            len(unique_terms),
            _MAX_QUERY_TERMS,
        )
        # SQL仍限制64个词元, 覆盖查询首尾，避免只截前半段丢掉末尾的处理要求。
        # 这里只缩减关键词通道，Embedding与回答模型仍接收完整规范化问题。
        last_index = len(unique_terms) - 1
        unique_terms = tuple(
            unique_terms[index * last_index // (_MAX_QUERY_TERMS - 1)]
            for index in range(_MAX_QUERY_TERMS)
        )
    return KeywordQuery(terms=unique_terms, search_text=" ".join(unique_terms))


# 文本文档预处理, 不是用户查询(保留原始内容和辅助检索词元)
def build_search_document(*, content: str, section_path: tuple[str, ...]) -> str:
    """保留可审查原文与章节标题, 并追加中文双字检索词元。"""

    source = unicodedata.normalize(
        "NFKC",
        f"{' '.join(section_path)}\n{content}",
    ).strip()
    bigrams: list[str] = []
    for match in _SEARCH_TOKEN_PATTERN.finditer(source):
        token = match.group(0)
        if _CJK_PATTERN.fullmatch(token) and len(token) >= 2:
            bigrams.extend(token[index : index + 2] for index in range(len(token) - 1))
    unique_bigrams = tuple(dict.fromkeys(bigrams))
    if not unique_bigrams:
        return source
    return f"{source}\n{' '.join(unique_bigrams)}"
