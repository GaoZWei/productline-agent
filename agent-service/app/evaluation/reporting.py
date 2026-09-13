"""统一评测报告、JSON/Markdown导出和两次报告对比。"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_VERSION_KEY_PATTERN = re.compile(_NAME_PATTERN)
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "content",
        "message",
        "password",
        "prompt",
        "secret",
        "token",
    }
)
_MARKDOWN_SKIPPED_FIELDS = frozenset({"confusion_matrix", "failures"})

# Subject类型枚举
class EvaluationSubjectKind(StrEnum):
    """明确区分可控替身、离线回放、集成环境和真实Provider。"""

    CONTROLLED = "CONTROLLED"
    REPLAY = "REPLAY"
    INTEGRATION = "INTEGRATION"
    LIVE_PROVIDER = "LIVE_PROVIDER"


class _ReportingSchema(BaseModel):
    """统一报告禁止额外字段、隐式转换和加载后修改。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

# 评测运行元数据模型
class EvaluationRunMetadata(_ReportingSchema):
    """一次评测的可追溯身份、Subject和数据版本。"""

    evaluation_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=r"^eval-[A-Za-z0-9._:-]+$"),
    ]
    generated_at: datetime
    subject_kind: EvaluationSubjectKind
    subject_name: Annotated[str, Field(min_length=1, max_length=128)]
    dataset_versions: dict[str, Annotated[str, Field(min_length=1, max_length=128)]]

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        """时间必须带时区, 数据集名称必须稳定且至少声明一个版本。"""

        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("evaluation generated_at must include timezone information")
        if not self.dataset_versions:
            raise ValueError("evaluation must declare at least one dataset version")
        if any(_VERSION_KEY_PATTERN.fullmatch(name) is None for name in self.dataset_versions):
            raise ValueError("evaluation dataset names must use stable identifiers")
        return self

# Suite统一外壳
class EvaluationSuiteResult(_ReportingSchema):
    """一个领域报告的统一外壳, payload仍保留领域Schema。"""

    suite_name: Annotated[str, Field(pattern=_NAME_PATTERN)]
    report_type: Annotated[str, Field(min_length=1, max_length=128)]
    total_cases: Annotated[int, Field(gt=0)] | None = None
    payload: dict[str, JsonValue]


class UnifiedEvaluationReport(_ReportingSchema):
    """可导出、可比较且不会混淆Subject来源的一次完整报告。"""

    schema_version: Literal["1.0"] = "1.0"
    metadata: EvaluationRunMetadata
    suites: Annotated[tuple[EvaluationSuiteResult, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_suites(self) -> Self:
        """同一次报告中每个Suite只能出现一次。"""

        names = tuple(suite.suite_name for suite in self.suites)
        if len(set(names)) != len(names):
            raise ValueError("evaluation suite results must have unique names")
        return self


class EvaluationMetricDelta(_ReportingSchema):
    """同一数值指标在两次报告间的原值和有符号变化。"""

    suite_name: Annotated[str, Field(pattern=_NAME_PATTERN)]
    metric_path: Annotated[str, Field(min_length=1, max_length=256)]
    baseline_value: float
    candidate_value: float
    delta: float


class EvaluationReportComparison(_ReportingSchema):
    """不擅自判断方向优劣的结构化报告差异。"""

    schema_version: Literal["1.0"] = "1.0"
    baseline_evaluation_id: str
    candidate_evaluation_id: str
    subject_changed: bool
    dataset_versions_changed: bool
    added_suites: tuple[str, ...] = ()
    removed_suites: tuple[str, ...] = ()
    changed_report_types: tuple[str, ...] = ()
    missing_metric_paths: tuple[str, ...] = ()
    metric_deltas: tuple[EvaluationMetricDelta, ...] = ()


class EvaluationReportError(ValueError):
    """统一报告包含不安全内容或无法按契约读写。"""


class EvaluationReportLoadError(EvaluationReportError):
    """统一报告文件无法读取或不满足Schema。"""


class EvaluationReportWriteError(EvaluationReportError):
    """统一报告无法写入目标路径。"""

# 构建统一报告
def build_unified_evaluation_report(
    metadata: EvaluationRunMetadata,
    reports: Mapping[str, BaseModel],
) -> UnifiedEvaluationReport:
    """按Runner顺序包装领域报告并拒绝敏感键。"""

    if not reports:
        raise EvaluationReportError("evaluation reports must be nonempty")
    missing_versions = tuple(
        suite_name
        for suite_name in reports
        if suite_name not in metadata.dataset_versions
    )
    if missing_versions:
        raise EvaluationReportError(
            f"evaluation dataset version is missing for suite: {missing_versions[0]}"
        )
    suites: list[EvaluationSuiteResult] = []
    for suite_name, report in reports.items():
        if not isinstance(report, BaseModel):
            raise EvaluationReportError("evaluation suite report must be a Pydantic model")
        payload = report.model_dump(mode="json")
        _validate_safe_payload(payload)
        total_cases = payload.get("total_cases")
        suites.append(
            EvaluationSuiteResult(
                suite_name=suite_name,
                report_type=type(report).__name__,
                total_cases=(
                    total_cases
                    if isinstance(total_cases, int) and not isinstance(total_cases, bool)
                    else None
                ),
                payload=payload,
            )
        )
    return UnifiedEvaluationReport(metadata=metadata, suites=tuple(suites))

# Json导出统一报告
def evaluation_report_json(report: UnifiedEvaluationReport) -> str:
    """生成字段稳定、UTF-8友好且以换行结束的JSON报告。"""

    return json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def write_evaluation_report_json(report: UnifiedEvaluationReport, path: Path) -> None:
    """创建父目录并写出统一JSON报告。"""

    _write_text(path, evaluation_report_json(report))


def load_evaluation_report(path: Path) -> UnifiedEvaluationReport:
    """从UTF-8 JSON读取统一报告并执行完整Schema校验。"""

    try:
        content = path.read_text(encoding="utf-8")
        report = UnifiedEvaluationReport.model_validate_json(content)
    except (OSError, UnicodeError, ValidationError, ValueError) as error:
        raise EvaluationReportLoadError("evaluation report could not be loaded") from error
    for suite in report.suites:
        _validate_safe_payload(suite.payload)
    return report

# Markdown导出统一报告
def evaluation_report_markdown(report: UnifiedEvaluationReport) -> str:
    """生成适合CI Artifact阅读的摘要和领域标量指标表。"""

    metadata = report.metadata
    lines = [
        f"# Evaluation report `{_markdown(metadata.evaluation_id)}`",
        "",
        f"- Generated at: `{metadata.generated_at.isoformat()}`",
        f"- Subject: `{metadata.subject_kind.value}/{_markdown(metadata.subject_name)}`",
        "- Dataset versions: "
        + ", ".join(
            f"`{_markdown(name)}={_markdown(version)}`"
            for name, version in sorted(metadata.dataset_versions.items())
        ),
    ]
    if metadata.subject_kind is not EvaluationSubjectKind.LIVE_PROVIDER:
        lines.extend(
            [
                "",
                "> This report does not represent live provider quality.",
            ]
        )
    for suite in report.suites:
        lines.extend(
            [
                "",
                f"## {_markdown(suite.suite_name)}",
                "",
                f"Report type: `{_markdown(suite.report_type)}`",
                "",
                "| Metric | Value |",
                "|---|---:|",
            ]
        )
        rows = tuple(_iter_scalar_metrics(suite.payload))
        lines.extend(
            f"| `{_markdown(path)}` | `{_markdown(_format_scalar(value))}` |"
            for path, value in rows
        )
        if not rows:
            lines.append("| `summary` | `no scalar metrics` |")
    return "\n".join(lines) + "\n"


def write_evaluation_report_markdown(
    report: UnifiedEvaluationReport,
    path: Path,
) -> None:
    """创建父目录并写出Markdown报告。"""

    _write_text(path, evaluation_report_markdown(report))

# 对比两个统一报告
def compare_evaluation_reports(
    baseline: UnifiedEvaluationReport,
    candidate: UnifiedEvaluationReport,
) -> EvaluationReportComparison:
    """按Suite和数值路径比较报告, 不猜测指标是越高还是越低越好。"""

    baseline_suites = {suite.suite_name: suite for suite in baseline.suites}
    candidate_suites = {suite.suite_name: suite for suite in candidate.suites}
    shared = tuple(name for name in baseline_suites if name in candidate_suites)
    changed_types = tuple(
        name
        for name in shared
        if baseline_suites[name].report_type != candidate_suites[name].report_type
    )
    missing_paths: list[str] = []
    deltas: list[EvaluationMetricDelta] = []
    for suite_name in shared:
        if suite_name in changed_types:
            continue
        baseline_metrics = dict(_iter_numeric_metrics(baseline_suites[suite_name].payload))
        candidate_metrics = dict(_iter_numeric_metrics(candidate_suites[suite_name].payload))
        for metric_path in sorted(baseline_metrics.keys() | candidate_metrics.keys()):
            qualified_path = f"{suite_name}.{metric_path}"
            if metric_path not in baseline_metrics or metric_path not in candidate_metrics:
                missing_paths.append(qualified_path)
                continue
            baseline_value = baseline_metrics[metric_path]
            candidate_value = candidate_metrics[metric_path]
            deltas.append(
                EvaluationMetricDelta(
                    suite_name=suite_name,
                    metric_path=metric_path,
                    baseline_value=baseline_value,
                    candidate_value=candidate_value,
                    delta=candidate_value - baseline_value,
                )
            )
    return EvaluationReportComparison(
        baseline_evaluation_id=baseline.metadata.evaluation_id,
        candidate_evaluation_id=candidate.metadata.evaluation_id,
        subject_changed=(
            baseline.metadata.subject_kind is not candidate.metadata.subject_kind
            or baseline.metadata.subject_name != candidate.metadata.subject_name
        ),
        dataset_versions_changed=(
            baseline.metadata.dataset_versions != candidate.metadata.dataset_versions
        ),
        added_suites=tuple(name for name in candidate_suites if name not in baseline_suites),
        removed_suites=tuple(name for name in baseline_suites if name not in candidate_suites),
        changed_report_types=changed_types,
        missing_metric_paths=tuple(missing_paths),
        metric_deltas=tuple(deltas),
    )


def evaluation_comparison_json(comparison: EvaluationReportComparison) -> str:
    """生成可供CI继续处理的确定性对比JSON。"""

    return json.dumps(
        comparison.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def write_evaluation_comparison_json(
    comparison: EvaluationReportComparison,
    path: Path,
) -> None:
    """创建父目录并写出结构化报告差异。"""

    _write_text(path, evaluation_comparison_json(comparison))


def _validate_safe_payload(value: JsonValue, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = key.lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                raise EvaluationReportError(
                    f"evaluation report contains forbidden field at {'.'.join((*path, key))}"
                )
            _validate_safe_payload(nested, path=(*path, key))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_safe_payload(nested, path=(*path, str(index)))


def _iter_scalar_metrics(
    value: JsonValue,
    *,
    prefix: str = "",
) -> Sequence[tuple[str, str | int | float | bool | None]]:
    rows: list[tuple[str, str | int | float | bool | None]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _MARKDOWN_SKIPPED_FIELDS:
                continue
            path = f"{prefix}.{key}" if prefix else key
            rows.extend(_iter_scalar_metrics(nested, prefix=path))
    elif not isinstance(value, list):
        rows.append((prefix, value))
    return rows


def _iter_numeric_metrics(
    value: JsonValue,
    *,
    prefix: str = "",
) -> Sequence[tuple[str, float]]:
    metrics: list[tuple[str, float]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _MARKDOWN_SKIPPED_FIELDS:
                continue
            path = f"{prefix}.{key}" if prefix else key
            metrics.extend(_iter_numeric_metrics(nested, prefix=path))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if math.isfinite(numeric):
            metrics.append((prefix, numeric))
    return metrics


def _format_scalar(value: str | int | float | bool | None) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return str(value)


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("`", "\\`")


def _write_text(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as error:
        raise EvaluationReportWriteError("evaluation report could not be written") from error
