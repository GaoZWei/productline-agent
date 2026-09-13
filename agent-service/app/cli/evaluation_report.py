"""统一评测报告离线渲染和两次报告对比CLI。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path

from app.evaluation.reporting import (
    EvaluationReportError,
    EvaluationReportWriteError,
    compare_evaluation_reports,
    load_evaluation_report,
    write_evaluation_comparison_json,
    write_evaluation_report_json,
    write_evaluation_report_markdown,
)


class EvaluationReportExitCode(IntEnum):
    """CI可稳定判断的报告命令退出码。"""

    SUCCESS = 0
    INPUT_ERROR = 2
    OUTPUT_ERROR = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="渲染或比较M7.8统一评测报告")
    commands = parser.add_subparsers(dest="command", required=True)

    render = commands.add_parser("render", help="校验JSON并渲染JSON或Markdown")
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--json-output", type=Path)
    render.add_argument("--markdown-output", type=Path)

    compare = commands.add_parser("compare", help="按Suite和数值路径比较两次报告")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行离线报告操作, 不访问模型、数据库或业务服务。"""

    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "render":
            if arguments.json_output is None and arguments.markdown_output is None:
                return _failure(
                    EvaluationReportExitCode.INPUT_ERROR,
                    "EVALUATION_OUTPUT_REQUIRED",
                )
            report = load_evaluation_report(arguments.input)
            if arguments.json_output is not None:
                write_evaluation_report_json(report, arguments.json_output)
            if arguments.markdown_output is not None:
                write_evaluation_report_markdown(report, arguments.markdown_output)
        else:
            baseline = load_evaluation_report(arguments.baseline)
            candidate = load_evaluation_report(arguments.candidate)
            comparison = compare_evaluation_reports(baseline, candidate)
            write_evaluation_comparison_json(comparison, arguments.output)
    except EvaluationReportWriteError:
        return _failure(
            EvaluationReportExitCode.OUTPUT_ERROR,
            "EVALUATION_REPORT_WRITE_FAILED",
        )
    except EvaluationReportError:
        return _failure(
            EvaluationReportExitCode.INPUT_ERROR,
            "EVALUATION_REPORT_INVALID",
        )

    print(json.dumps({"ok": True, "command": arguments.command}, sort_keys=True))
    return EvaluationReportExitCode.SUCCESS


def _failure(exit_code: EvaluationReportExitCode, error_code: str) -> int:
    """只向CI输出稳定错误码, 不回显报告或文件内容。"""

    print(json.dumps({"ok": False, "error_code": error_code}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
