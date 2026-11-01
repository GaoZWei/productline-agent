"""使用目录文件描述符保存独立原件，拒绝符号链接、路径逃逸及原件覆盖。"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.knowledge.loaders import DocumentLoadError, normalize_document_content
from app.schemas.knowledge_management import KnowledgeManagementError

MAX_ORIGINAL_BYTES = 10 * 1024 * 1024
_KEY = re.compile(
    r"versions/([A-Z][A-Z0-9]*-[0-9A-F]{32})/revisions/([1-9][0-9]*)/original\.(md|txt)"
)


@dataclass(frozen=True, slots=True)
class StagedOriginal:
    """仅服务端使用的临时文件身份及校验结果，不出现在对外结果中。"""

    name: str
    filename: str
    file_format: Literal["MD", "TXT"]
    byte_size: int
    raw_hash: str


class KnowledgeOriginalStorage:
    """惰性创建受控目录，文件原子提交在数据库事务之外完成。"""

    def __init__(self, root: Path) -> None:
        self.root = root.absolute()

    def _directory(self, parts: tuple[str, ...], *, create: bool = False) -> int:
        """每一级使用NOFOLLOW打开，目录替换不会把访问引向外部路径。"""

        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in (*self.root.parts[1:], *parts):
                if part in {"", ".", ".."} or "/" in part or "\\" in part:
                    raise KnowledgeManagementError("INVALID_STORAGE_PATH")
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _parts(key: str) -> tuple[str, ...]:
        """只接受服务端版本/修订生成的规范key。"""

        if _KEY.fullmatch(key) is None:
            raise KnowledgeManagementError("INVALID_STORAGE_PATH")
        return tuple(key.split("/"))

    async def stage(self, chunks: AsyncIterable[bytes], filename: str) -> StagedOriginal:
        """按流限制字节数，保存原字节并在提交前校验UTF-8与非空内容。"""

        suffix = Path(filename).suffix.lower()
        if any(char in filename for char in ("/", "\\")) or any(
            ord(char) < 32 or ord(char) == 127 for char in filename
        ):
            raise KnowledgeManagementError("INVALID_FILENAME")
        if suffix not in {".md", ".txt"}:
            raise KnowledgeManagementError("UNSUPPORTED_FORMAT")
        name = uuid4().hex + ".part"
        directory = -1
        descriptor = -1
        try:
            directory = self._directory(("_temporary",), create=True)
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
            )
            digest = hashlib.sha256()
            size = 0
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise KnowledgeManagementError("INVALID_UPLOAD_STREAM")
                size += len(chunk)
                if size > MAX_ORIGINAL_BYTES:
                    raise KnowledgeManagementError("FILE_TOO_LARGE")
                digest.update(chunk)
                remaining = memoryview(chunk)
                while remaining:
                    written = os.write(descriptor, remaining)
                    remaining = remaining[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            staged = StagedOriginal(
                name, filename, "MD" if suffix == ".md" else "TXT", size, digest.hexdigest()
            )
            data = self._read(directory, name)
            try:
                decoded = data.decode("utf-8")
                if "\x00" in decoded:
                    raise KnowledgeManagementError("INVALID_TEXT_CONTENT")
                normalize_document_content(decoded)
            except UnicodeDecodeError:
                raise KnowledgeManagementError("INVALID_ENCODING") from None
            except DocumentLoadError:
                raise KnowledgeManagementError("EMPTY_DOCUMENT") from None
            return staged
        except BaseException as error:
            if descriptor >= 0:
                os.close(descriptor)
            if directory >= 0:
                try:
                    os.unlink(name, dir_fd=directory)
                except FileNotFoundError:
                    pass
            if isinstance(error, OSError):
                raise KnowledgeManagementError("STORAGE_ERROR") from None
            if isinstance(error, Exception) and not isinstance(error, KnowledgeManagementError):
                raise KnowledgeManagementError("INVALID_UPLOAD_STREAM") from None
            raise
        finally:
            if directory >= 0:
                os.close(directory)

    def _read(self, directory: int, name: str) -> bytes:
        """限长读取普通文件，不打开符号链接、目录或设备。"""

        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise KnowledgeManagementError("INVALID_STORAGE_PATH")
            data = source.read(MAX_ORIGINAL_BYTES + 1)
        if len(data) > MAX_ORIGINAL_BYTES:
            raise KnowledgeManagementError("FILE_TOO_LARGE")
        return data

    def commit(self, staged: StagedOriginal, key: str) -> None:
        """同文件系统硬链接原子创建最终原件，已有文件仅在哈希一致时复用。"""

        parts = self._parts(key)
        if re.fullmatch(r"[0-9a-f]{32}\.part", staged.name) is None:
            raise KnowledgeManagementError("INVALID_STORAGE_PATH")
        if parts[-1] != ("original.md" if staged.file_format == "MD" else "original.txt"):
            raise KnowledgeManagementError("INVALID_STORAGE_PATH")
        source_directory = -1
        target_directory = -1
        try:
            source_directory = self._directory(("_temporary",))
            target_directory = self._directory(parts[:-1], create=True)
            data = self._read(source_directory, staged.name)
            if len(data) != staged.byte_size or hashlib.sha256(data).hexdigest() != staged.raw_hash:
                raise KnowledgeManagementError("ORIGINAL_INTEGRITY_ERROR")
            try:
                os.link(
                    staged.name,
                    parts[-1],
                    src_dir_fd=source_directory,
                    dst_dir_fd=target_directory,
                    follow_symlinks=False,
                )
            except FileExistsError:
                existing = self._read(target_directory, parts[-1])
                if existing != data:
                    raise KnowledgeManagementError("ORIGINAL_CONFLICT") from None
            if self._read(target_directory, parts[-1]) != data:
                raise KnowledgeManagementError("ORIGINAL_INTEGRITY_ERROR")
            os.fsync(target_directory)
        except OSError:
            raise KnowledgeManagementError("STORAGE_ERROR") from None
        finally:
            if source_directory >= 0:
                os.close(source_directory)
            if target_directory >= 0:
                os.close(target_directory)

    def discard(self, staged: StagedOriginal) -> None:
        """只清理本次随机临时文件，不删除已提交或未引用的原件。"""

        if re.fullmatch(r"[0-9a-f]{32}\.part", staged.name) is None:
            raise KnowledgeManagementError("INVALID_STORAGE_PATH")
        directory = -1
        try:
            directory = self._directory(("_temporary",))
            os.unlink(staged.name, dir_fd=directory)
        except FileNotFoundError:
            pass
        except OSError:
            raise KnowledgeManagementError("STORAGE_ERROR") from None
        finally:
            if directory >= 0:
                os.close(directory)

    def read(self, key: str, raw_hash: str, byte_size: int) -> bytes:
        """只能用数据库中的key及原始摘要读取，缺失时不回退固定语料。"""

        parts = self._parts(key)
        directory = -1
        try:
            directory = self._directory(parts[:-1])
            data = self._read(directory, parts[-1])
            if len(data) != byte_size or hashlib.sha256(data).hexdigest() != raw_hash:
                raise KnowledgeManagementError("ORIGINAL_INTEGRITY_ERROR")
            return data
        except FileNotFoundError:
            raise KnowledgeManagementError("ORIGINAL_NOT_FOUND") from None
        except OSError:
            raise KnowledgeManagementError("STORAGE_ERROR") from None
        finally:
            if directory >= 0:
                os.close(directory)
