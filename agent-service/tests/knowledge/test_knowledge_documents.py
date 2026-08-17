"""M4.1 演示规范目录、元数据和版本关系测试。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_KNOWLEDGE_ROOT = _REPOSITORY_ROOT / "knowledge-base"
_CATALOG_PATH = _KNOWLEDGE_ROOT / "catalog.json"
_EXPECTED_ACTIVE_COUNTS = {
    "DOM_PRODUCT_SPEC": 3,
    "QUALITY_SPEC": 4,
    "COORDINATE_SYSTEM_SPEC": 2,
    "REVIEW_OPERATION_SPEC": 2,
    "DELIVERY_SPEC": 3,
}
# 八个计划元数据字段
_REQUIRED_METADATA_FIELDS = {
    "document_type",  # 文档业务类型
    "satellite_type",  # 当前固定为GF-2
    "product_type",  # 当前固定为DOM
    "processing_level",  # 当前固定为L2
    "specification_version",  # 规范自身版本
    "effective_date",  # 开始生效的日期
    "expiry_date",  # 过期日期
    "permission_scope",  # 权限范围
}


def _load_catalog() -> list[dict[str, Any]]:
    payload = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    documents = payload["documents"]
    assert isinstance(documents, list)
    return documents


@pytest.mark.unit
def test_catalog_contains_planned_active_and_historical_documents() -> None:
    documents = _load_catalog()
    active = [document for document in documents if document["lifecycle"] == "ACTIVE"]
    historical = [
        document for document in documents if document["lifecycle"] == "HISTORICAL"
    ]

    assert len(documents) == 16
    assert Counter(document["document_type"] for document in active) == Counter(
        _EXPECTED_ACTIVE_COUNTS
    )
    assert len(historical) == 2


@pytest.mark.unit
def test_catalog_metadata_paths_and_demo_markers_are_stable() -> None:
    documents = _load_catalog()
    document_ids: set[str] = set()
    file_paths: set[str] = set()

    for document in documents:
        assert _REQUIRED_METADATA_FIELDS <= document.keys()
        assert document["document_id"] not in document_ids
        assert document["file_path"] not in file_paths
        document_ids.add(document["document_id"])
        file_paths.add(document["file_path"])

        relative_path = PurePosixPath(document["file_path"])
        assert not relative_path.is_absolute()
        assert ".." not in relative_path.parts
        expected_parent = (
            "active" if document["lifecycle"] == "ACTIVE" else "historical"
        )
        assert relative_path.parts[0] == expected_parent

        markdown_path = _KNOWLEDGE_ROOT.joinpath(*relative_path.parts)
        content = markdown_path.read_text(encoding="utf-8")
        assert markdown_path.suffix == ".md"
        assert content.startswith("# ")
        assert "> 演示规范数据，非真实行业标准。" in content  # noqa: RUF001
        assert len(content.splitlines()) >= 12

    cataloged_markdown = {(_KNOWLEDGE_ROOT / path).resolve() for path in file_paths}
    actual_markdown = {
        path.resolve()
        for path in _KNOWLEDGE_ROOT.rglob("*.md")
        if path.name != "README.md"
    }
    assert actual_markdown == cataloged_markdown


@pytest.mark.unit
def test_document_dates_and_historical_replacements_are_consistent() -> None:
    documents = _load_catalog()
    documents_by_id = {document["document_id"]: document for document in documents}

    for document in documents:
        effective_date = date.fromisoformat(document["effective_date"])
        expiry_value = document["expiry_date"]
        if document["lifecycle"] == "ACTIVE":
            assert expiry_value is None
            assert document["replaced_by"] is None
            continue

        expiry_date = date.fromisoformat(expiry_value)
        assert effective_date <= expiry_date
        replacement = documents_by_id[document["replaced_by"]]
        assert replacement["lifecycle"] == "ACTIVE"
        assert replacement["document_type"] == document["document_type"]
        assert date.fromisoformat(replacement["effective_date"]) > expiry_date
