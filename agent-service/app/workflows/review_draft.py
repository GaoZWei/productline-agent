"""M6.3基于最新事实和现行规范生成可确认复核草稿。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from app.models import AgentRunStatus, ApprovalStatus
from app.schemas.approval import ReviewDraft
from app.schemas.business import BusinessIdentity
from app.schemas.context import PageContext
from app.schemas.knowledge import Citation, PermissionScope
from app.schemas.specification import SpecificationQaResult, SpecificationQaStatus
from app.schemas.tools import QualityIssue, QualityIssueList, TaskDetail
from app.schemas.workflow import DiagnosisResult
from app.tools import ToolContext, ToolResult


# 历史诊断Run的最小快照
@dataclass(frozen=True, slots=True)
class ReviewDraftRunSnapshot:
    """最近一次诊断Run中生成草稿所需的最小只读快照。"""

    run_id: str
    status: AgentRunStatus
    final_result: dict[str, Any] | None  # 当时生成的诊断结果


@dataclass(frozen=True, slots=True)
class ReviewDraftPersistenceResult:
    """草稿和Run状态原子保存后的稳定结果。"""

    approval_id: str
    approval_status: ApprovalStatus
    run_status: AgentRunStatus

# 模型输入参数
@dataclass(frozen=True, slots=True)
class ReviewDraftGenerationModelRequest:
    """草稿模型只读取已验证诊断、最新Java事实和当前规范引用。"""

    diagnosis: DiagnosisResult  # 已验证诊断结果
    task: TaskDetail
    quality_issues: tuple[QualityIssue, ...]
    specification_answer: str
    citations: tuple[Citation, ...]  # RAG安全过滤和引用构建后的规范引用

# 模型输出结果
@dataclass(frozen=True, slots=True)
class ReviewDraftGenerationResult:
    """返回页面后续确认流程所需的Approval身份和原始草稿。"""

    approval_id: str
    run_id: str
    approval_status: ApprovalStatus
    run_status: AgentRunStatus
    draft: ReviewDraft


class ReviewDraftStore(Protocol):
    """隔离Workflow与具体数据库事务实现的最小持久化协议。"""

    def latest_diagnosis(
        self,
        session_id: str,
        *,
        identity: BusinessIdentity,
    ) -> Awaitable[ReviewDraftRunSnapshot | None]: ...

    def save_waiting_approval(
        self,
        *,
        approval_id: str,
        run_id: str,
        draft: ReviewDraft,
        target_version: int,
    ) -> Awaitable[ReviewDraftPersistenceResult]: ...


class ReviewDraftTool(Protocol):
    """Workflow只需要Tool的受控执行入口。"""

    def execute(
        self,
        raw_input: Mapping[str, object],
        context: ToolContext,
        *,
        force_refresh: bool = False,
    ) -> Awaitable[ToolResult[Any]]: ...


class ReviewDraftToolRegistry(Protocol):
    """按稳定名称提供草稿生成所需的只读Tool。"""

    def get(self, name: str) -> ReviewDraftTool: ...


class ReviewDraftSpecificationWorkflow(Protocol):
    """以显式日期和权限返回带状态的现行规范结果。"""

    def ainvoke(
        self,
        question: str,
        *,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
    ) -> Awaitable[SpecificationQaResult]: ...


class ReviewDraftGenerationModel(Protocol):
    """模型适配器必须返回可由ReviewDraft严格校验的结构化对象。"""

    def generate(self, request: ReviewDraftGenerationModelRequest) -> Awaitable[object]:
        """根据受控输入生成草稿, 不获得任何Tool执行入口。"""


class ReviewDraftGenerationError(Exception):
    """草稿生成在持久化前关闭失败的错误基类。"""


class ReviewDraftSourceError(ReviewDraftGenerationError):
    """最近诊断不存在、状态不允许或结果结构不可识别。"""


class ReviewDraftBusinessFactError(ReviewDraftGenerationError):
    """最新Java只读事实不可用或与诊断目标不一致。"""


class ReviewDraftSpecificationError(ReviewDraftGenerationError):
    """当前规范检索未形成可引用依据。"""


class InvalidReviewDraftOutputError(ReviewDraftGenerationError):
    """模型草稿改变目标、引用未知来源或不满足ReviewDraft契约。"""


def _new_approval_id() -> str:
    return f"approval-{uuid4().hex}"


class ReviewDraftGenerationWorkflow:
    """固定执行“旧诊断→新事实→现行规范→草稿→等待确认”的安全链路。"""

    def __init__(
        self,
        *,
        store: ReviewDraftStore,
        tool_registry: ReviewDraftToolRegistry,
        tool_context: ToolContext,
        specification_workflow: ReviewDraftSpecificationWorkflow,
        draft_model: ReviewDraftGenerationModel,
        effective_at: date,
        permission_scope: PermissionScope,
        page_context: PageContext | None = None,
        approval_id_factory: Callable[[], str] = _new_approval_id,
    ) -> None:
        self._store = store
        self._tool_registry = tool_registry
        self._tool_context = tool_context
        self._specification_workflow = specification_workflow
        self._draft_model = draft_model
        self._effective_at = effective_at
        self._permission_scope = permission_scope
        self._page_context = page_context
        self._approval_id_factory = approval_id_factory
        self._invoked = False
    # 主流程
    async def ainvoke(
        self,
        *,
        session_id: str,
        task_id: str,
    ) -> ReviewDraftGenerationResult:
        """生成并保存一份WAITING_CONFIRMATION草稿, 过程中不调用写Tool。"""
        # 第一步：限制一个Workflow实例只能运行一次
        if self._invoked:
            raise RuntimeError("one review draft workflow instance can only execute once")
        self._invoked = True
        # 第二步：读取最近诊断Run的快照
        source = await self._store.latest_diagnosis(  # 定位最近一个带结果的Run
            session_id,
            identity=self._tool_context.identity,
        )
        diagnosis = self._parse_source_diagnosis(source)
        if source is None:  # pragma: no cover - 已由解析函数关闭失败
            raise AssertionError("source diagnosis must exist")
        if self._tool_context.run_id != source.run_id:
            raise ReviewDraftSourceError("ToolContext run_id must match recent diagnosis run")
        # 第三步：必须重新调用Java Tool   
        task = await self._read_task(task_id)
        issues = await self._read_quality_issues(task_id)
        # 查询完成后还会校验，防止串线问题
        if task.order_id != diagnosis.order_id:
            raise ReviewDraftBusinessFactError(
                "latest task order does not match the recent diagnosis order"
            )
        # 第四步：规范检索
        specification = await self._retrieve_specification(task, issues.issues)
        # 第五步：构造草稿请求
        request = ReviewDraftGenerationModelRequest(
            diagnosis=diagnosis,
            task=task,
            quality_issues=tuple(sorted(issues.issues, key=lambda issue: issue.issue_id)),
            specification_answer=specification.answer,
            citations=specification.citations,
        )
        # 第六步：生成草稿
        draft = self._parse_draft(await self._draft_model.generate(request))
        self._validate_draft(
            draft,
            task=task,
            issues=issues.issues,
            citations=specification.citations,
        )

        approval_id = self._approval_id_factory()
        persisted = await self._store.save_waiting_approval(
            approval_id=approval_id,
            run_id=source.run_id,
            draft=draft,
            target_version=task.version,
        )
        return ReviewDraftGenerationResult(
            approval_id=persisted.approval_id,
            run_id=source.run_id,
            approval_status=persisted.approval_status,
            run_status=persisted.run_status,
            draft=draft,
        )

    @staticmethod
    def _parse_source_diagnosis(
        source: ReviewDraftRunSnapshot | None,
    ) -> DiagnosisResult:
        if source is None:
            raise ReviewDraftSourceError("recent diagnosis result was not found")
        if source.status is not AgentRunStatus.SUCCEEDED:
            raise ReviewDraftSourceError("recent diagnosis Run must be SUCCEEDED")
        if source.final_result is None:
            raise ReviewDraftSourceError("recent diagnosis result is invalid")
        try:  # 历史诊断要用JSON模式恢复模型输出
            return DiagnosisResult.model_validate_json(
                json.dumps(source.final_result, ensure_ascii=False, allow_nan=False)
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ReviewDraftSourceError("recent diagnosis result is invalid") from error
    # 只调用两个只读Tool获取任务详情和质检问题列表
    async def _read_task(self, task_id: str) -> TaskDetail:
        result = await self._execute_read_tool("get_task_detail", task_id)
        if not isinstance(result, TaskDetail) or result.task_id != task_id:
            raise ReviewDraftBusinessFactError("get_task_detail returned an unrecognized task fact")
        return result

    async def _read_quality_issues(self, task_id: str) -> QualityIssueList:
        result = await self._execute_read_tool("get_quality_issues", task_id)
        if not isinstance(result, QualityIssueList) or result.task_id != task_id:
            raise ReviewDraftBusinessFactError(
                "get_quality_issues returned unrecognized quality facts"
            )
        return result

    async def _execute_read_tool(self, tool_name: str, task_id: str) -> object:
        tool = self._tool_registry.get(tool_name)
        result = await tool.execute(
            {"task_id": task_id},
            self._tool_context,
            force_refresh=True,
        )
        if not result.success or result.data is None:
            code = result.error.code.value if result.error is not None else "UNKNOWN"
            raise ReviewDraftBusinessFactError(f"{tool_name} failed with {code}")
        return result.data
    # 规范检索
    async def _retrieve_specification(
        self,
        task: TaskDetail,
        issues: list[QualityIssue],
    ) -> SpecificationQaResult:
        result = await self._specification_workflow.ainvoke(
            _build_specification_question(task, issues),
            effective_at=self._effective_at,
            permission_scope=self._permission_scope,
            page_context=self._page_context,
        )
        if result.status is not SpecificationQaStatus.ANSWERED or not result.citations:
            raise ReviewDraftSpecificationError(
                "current citations are required before generating a review draft"
            )
        return result
    # 解析草稿输出
    @staticmethod
    def _parse_draft(raw_output: object) -> ReviewDraft:
        try:
            if isinstance(raw_output, (str, bytes, bytearray)):
                return ReviewDraft.model_validate_json(raw_output)
            # 校验模型输出是否符合预期
            return ReviewDraft.model_validate(raw_output)
        except ValidationError as error:
            raise InvalidReviewDraftOutputError("review draft schema validation failed") from error
    # 第二层校验：任务和Citation白名单
    @staticmethod
    def _validate_draft(
        draft: ReviewDraft,
        *,
        task: TaskDetail,
        issues: list[QualityIssue],
        citations: tuple[Citation, ...],
    ) -> None:
        # 模型不能替换任务ID
        if draft.task_id != task.task_id:
            raise InvalidReviewDraftOutputError("review draft changed the target task")
        # issue_id存在并且与任务ID匹配
        if not any(
            issue.issue_id == draft.issue_id and issue.task_id == task.task_id
            for issue in issues
        ):
            raise InvalidReviewDraftOutputError("review draft referenced an unknown quality issue")
        # 草稿必须至少有一个现行规范引用
        if not draft.specification_references:
            raise InvalidReviewDraftOutputError(
                "review draft must cite at least one current specification"
            )
        allowed = {
            (citation.document_id, citation.document_version, citation.chunk_ids): citation
            for citation in citations
        }
        # 草稿引用必须来自RAG结果中的规范
        for reference in draft.specification_references:
            identity = (
                reference.document_id,
                reference.document_version,
                reference.chunk_ids,
            )
            if allowed.get(identity) != reference:
                raise InvalidReviewDraftOutputError(
                    "review draft referenced an unknown or changed citation"
                )

# 构造检索问题
def _build_specification_question(
    task: TaskDetail,
    issues: list[QualityIssue],
) -> str:
    """只使用稳定问题类型构造有界检索问题, 不复制任意长业务描述。"""

    current = sorted(
        {
            f"{issue.issue_type}({issue.status})"
            for issue in issues
            if issue.status in {"OPEN", "PROCESSING"}
        }
    )
    issue_summary = "、".join(current) if current else "无未解决质检问题"
    return f"生产任务{task.task_id}存在{issue_summary}时, 应如何形成复核结论和处理意见?"
