"""显式执行的小额真实Provider检查, 不建立数据库连接或执行业务流程。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.clients.model import ChatMessage, ModelClientError, OpenAICompatibleChatClient
from app.knowledge.embeddings import (
    EmbeddingConfig,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingProvider,
)
from app.settings import Settings

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
SmokeTarget = Literal["all", "chat", "embedding"]


class SmokeOutput(BaseModel):
    """只检查最小结构化输出契约, 不让模型选择或调用业务能力。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["ok"]

# 检查模型能否按要求返回 JSON 格式输出
async def _check_chat(
    settings: Settings, transport: httpx.AsyncBaseTransport | None,
) -> dict[str, object]:
    """发送一个固定请求, 返回脱敏统计并确保连接关闭。"""
    # 先限制本次调用预算
    # 烟测不自动重试, 并收紧单次输出和等待预算; 不修改生产Settings。
    smoke_settings = settings.model_copy(update={
        "model_max_retries": 0,
        "model_max_output_tokens": min(settings.model_max_output_tokens, 64),
        "model_timeout_seconds": min(settings.model_timeout_seconds, 30.0),
    })
    client = OpenAICompatibleChatClient(smoke_settings, transport=transport)
    try:  
        # 再发送固定请求
        result = await client.complete_structured(
            (ChatMessage(role="user", content='Return only this JSON object: {"status":"ok"}'),),
            SmokeOutput,  # 本地校验规则
        )
        return {
            "returned_model": result.model_name,
            "model_matches": result.model_name == settings.model_name,
            "input_tokens": result.token_usage.input_tokens,
            "output_tokens": result.token_usage.output_tokens,
            "total_tokens": result.token_usage.total_tokens,
        }
    finally:
        await client.aclose()

# 检查向量生成和返回契约
async def _check_embedding(
    settings: Settings, transport: httpx.AsyncBaseTransport | None,
) -> dict[str, object]:
    """生成一句公开测试文本的向量, 只返回元数据而不保存向量。"""

    config = EmbeddingConfig.from_settings(settings)
    config = config.model_copy(update={
        "max_retries": 0,
        "timeout_seconds": min(config.timeout_seconds, 30.0),
    })
    provider = OpenAICompatibleEmbeddingProvider(config, transport=transport)
    try:
        result = await provider.embed_with_usage(("坐标系问题处理完成后，应重新提交复核。",))
        if result.model_name != config.model:
            return {"status": "failed", "error_code": "EMBEDDING_MODEL_MISMATCH"}
        return {
            "returned_model": result.model_name,
            "model_matches": True,
            "vector_count": len(result.vectors),
            "dimension": len(result.vectors[0]),
            "input_tokens": result.input_tokens,
            "total_tokens": result.total_tokens,
        }
    finally:
        await provider.aclose()
# 统一执行和收集失败信息 （运行冒烟测试）
async def run_smoke(
    settings: Settings,
    *,
    target: SmokeTarget = "all",
    chat_transport: httpx.AsyncBaseTransport | None = None,
    embedding_transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    """顺序检查选定Provider; 单项失败不掩盖另一项, 不依赖Java或数据库。"""

    checks: list[dict[str, object]] = []
    # 负责循环检查选中的 Provider 是否符合契约
    targets = ("chat", "embedding") if target == "all" else (target,)
    for name in targets:
        check: dict[str, object] = {
            "target": name,
            "status": "passed",
            "requested_model": settings.model_name if name == "chat" else settings.embedding_model,
        }
        started_at = time.monotonic()
        try:
            if name == "chat":
                check.update(await _check_chat(settings, chat_transport))
            else:
                check.update(await _check_embedding(settings, embedding_transport))
        # 每一项都单独捕获错误, 避免隐藏其他项的失败
        except (ModelClientError, EmbeddingProviderError) as error:
            check.update({
                "status": "failed",
                "error_code": error.code.value,
                "retryable": error.retryable,
                "http_status": error.status_code,
            })
        except ValueError:
            check.update({"status": "failed", "error_code": "PROVIDER_CONFIGURATION_ERROR"})
        except Exception:
            # 不输出异常正文或traceback, 防止URL、供应商正文和密钥进入终端。
            check.update({"status": "failed", "error_code": "PROVIDER_SMOKE_INTERNAL_ERROR"})
        check["duration_ms"] = max(0, int((time.monotonic() - started_at) * 1000))
        checks.append(check)
    return {
        "success": all(check["status"] == "passed" for check in checks),
        "checks": checks,
        "automatic_retries": 0,
    }

# 命令入口和配置加载函数
def main(argv: Sequence[str] | None = None) -> int:
    """读取指定环境文件并输出JSON; 成功为0, 配置错误为2, 检查失败为3。"""

    parser = argparse.ArgumentParser(description="只读真实Provider烟测, 会产生少量Token消耗")
    # 解析 --target	选择检查 chat、embedding 或两者都检查
    parser.add_argument("--target", choices=("all", "chat", "embedding"), default="all")
    # 加载 Settings	默认读取仓库根 .env，也可以指定其他配置文件；进程环境变量优先
    parser.add_argument("--env-file", type=Path, help="默认读取仓库根.env; 进程环境变量优先")
    arguments = parser.parse_args(argv)
    # 独立CLI只输出白名单JSON, 不让HTTP日志额外记录网关地址。
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        try:
            if arguments.env_file is not None and not arguments.env_file.is_file():
                raise ValueError("environment file is unavailable")
            # 加载配置文件
            settings = Settings(_env_file=arguments.env_file or DEFAULT_ENV_FILE)
        # 配置文件或配置校验失败
        except (OSError, ValueError, ValidationError):
            print(json.dumps({"success": False, "error_code": "PROVIDER_CONFIGURATION_ERROR"}))
            return 2
        # 执行 run_smoke()	进入异步检查流程，取得报告
        report = asyncio.run(run_smoke(settings, target=arguments.target))
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["success"] else 3
    finally:
        logging.disable(previous_disable)


if __name__ == "__main__":
    raise SystemExit(main())
