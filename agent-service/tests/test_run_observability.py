"""M7.1 Run Token统计的严格契约测试。"""

import pytest
from pydantic import ValidationError

from app.schemas import RunTokenUsage


@pytest.mark.unit
def test_run_token_usage_builds_exact_total() -> None:
    usage = RunTokenUsage.from_counts(input_tokens=120, output_tokens=30)

    assert usage.input_tokens == 120
    assert usage.output_tokens == 30
    assert usage.total_tokens == 150


@pytest.mark.unit
@pytest.mark.parametrize(
    "values",
    [
        {"input_tokens": -1, "output_tokens": 0, "total_tokens": -1},
        {"input_tokens": 1, "output_tokens": 2, "total_tokens": 4},
        {"input_tokens": True, "output_tokens": 0, "total_tokens": 1},
    ],
)
def test_run_token_usage_rejects_negative_inconsistent_or_coerced_counts(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RunTokenUsage.model_validate(values)
