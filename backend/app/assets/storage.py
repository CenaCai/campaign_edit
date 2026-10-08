"""资产存储适配器。

为什么用适配器而不是直接写死本地磁盘：
导出产物里的图片最终一定要落到某个可访问的地方。本地磁盘适合开发与内网，
但生产多半是 S3/OSS/MinIO。把"存"这件事抽象出来后，换后端不改业务代码。

设计要点
--------
* **key 一律用 ``asset/<yyyy-mm>/<hash>.<ext>`` 形式的相对键**，不含盘符/域名。
  这样换存储后端时历史 key 依然有效，只是解析方式变了。
* **同名文件按内容哈希去重**：同一张 logo 被 20 封邮件引用只存一份。
* **local 后端零依赖**（标准库），S3 后端延迟import boto3 —— 没装也能跑。
* 所有写入都是"先写临时文件再原子改名"，避免半截文件被引用。
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings

# 允许的图片类型（不含svg 的原因见check_mime）
_SAFE_MIMES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
}

_MIME_EXT = {v: k for k, v in _SAFE_MIMES.items()}


class AssetError(RuntimeError):
    pass


def now_ym() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def build_key(filename: str, data: bytes) -> str:
    """内容哈希 + 原扩展名 → 稳定且去重的相对键。"""
    digest = hashlib.sha256(data).hexdigest()[:16]
    ext = _ext_of(filename)
    return f"asset/{now_ym()}/{digest}{ext}"


def _ext_of(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext and len(ext) <= 6 and ext.isascii():
        return ext
    return ".bin"


def guess_mime(filename: str, declared: str = "", data: bytes = b"") -> str:
    """推断 MIME。优先级：内容魔数 > 声明的 MIME > 扩展名。

    注意 data 默认为空——调用方可能只��有文件名（如批量导入历史数据）。
    """
    if data:
        sniffed = sniff_mime(filename, data)
        if sniffed:
            return sniffed
    d = (declared or "").split(";")[0].strip().lower()
    if d in _SAFE_MIMES:
        return d
    guessed, _ = mimetypes.guess_type(filename or "")
    if guessed in _SAFE_MIMES:
        return guessed
    return ""


def sniff_mime(filename: str = "", data: bytes | None = None) -> str:
    """按魔数识别图片类型——比信任扩展名可靠。"""
    if not data:
        return ""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return "image/avif"
    head = data[:256].lstrip()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:1024]):
        return "image/svg+xml"
    return ""


def image_size(mime: str, data: bytes) -> tuple[int, int] | None:
    """从文件头解析尺寸。PNG/JPEG/GIF/WebP/AVIF，纯标准库实现（不引 Pillow）。"""
    try:
        if mime == "image/png" and len(data) >= 24:
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if mime == "image/gif" and len(data) >= 10:
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        if mime == "image/jpeg":
            return _jpeg_size(data)
        if mime == "image/webp" and len(data) >= 30:
            return _webp_size(data)
    except Exception:
        return None
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # SOF0..SOF3 / SOF5..SOF7 / SOF9..SOF11 / SOF13..SOF15
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h
        seg = int.from_bytes(data[i + 2:i + 4], "big")
        if seg <= 0:
            return None
        i += 2 + seg
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30:
        return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF)
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X" and len(data) >= 30:
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    return None


def check_allowed(mime: str, size: int, data: bytes = b"") -> None:
    """上传校验。大小、类型、SVG 安全性三道关。"""
    if size <= 0:
        raise AssetError("文件为空")
    if size > settings.asset_max_bytes:
        raise AssetError(
            f"文件超过上限（{size / 1024 / 1024:.1f}MB > "
            f"{settings.asset_max_bytes / 1024 / 1024:.0f}MB）")
    allowed = {m.strip() for m in settings.asset_allowed_mimes.split(",") if m.strip()}
    if mime not in allowed:
        raise AssetError(f"不支持的类型 {mime}；允许：{', '.join(sorted(allowed))}")
    if mime == "image/svg+xml" and data and not svg_is_safe(data):
        raise AssetError(
            "SVG 包含脚本或外链（<script>/javascript:/onload 等），拒绝上传。"
            "请在导出前做净化，或改用 PNG/WebP。")


# ---------------------------------------------------------------- 适配器

class StorageAdapter(ABC):
    name = "base"

    @abstractmethod
    def write(self, key: str, data: bytes) -> str:
        """写入并返回访问 URL。"""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def read(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> bool: ...

    @abstractmethod
    def url(self, key: str) -> str: ...

    @abstractmethod
    def size(self, key: str) -> int: ...


class LocalStorage(StorageAdapter):
    """本地磁盘。适合开发、内网、以及对象存储接入前的过渡。"""

    name = "local"

    def __init__(self, root: str | None = None, url_prefix: str | None = None,
                 base_url: str | None = None) -> None:
        self.root = Path(root or settings.asset_dir).resolve()
        self.url_prefix = (url_prefix or settings.asset_url_prefix).rstrip("/")
        self.base_url = (base_url or settings.export_base_url).rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        """防路径穿越：解析后必须仍在 root 内。"""
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root)):
            raise AssetError(f"非法路径: {key}")
        return p

    def write(self, key: str, data: bytes) -> str:
        p = self._safe_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)          # 原子改名，避免半截文件
        return self.url(key)

    def exists(self, key: str) -> bool:
        try:
            return self._safe_path(key).is_file()
        except AssetError:
            return False

    def read(self, key: str) -> bytes:
        p = self._safe_path(key)
        if not p.is_file():
            raise AssetError(f"资产不存在: {key}")
        return p.read_bytes()

    def delete(self, key: str) -> bool:
        p = self._safe_path(key)
        if p.is_file():
            p.unlink()
            return True
        return False

    def size(self, key: str) -> int:
        p = self._safe_path(key)
        return p.stat().st_size if p.is_file() else 0

    def url(self, key: str) -> str:
        return f"{self.base_url}{self.url_prefix}/{key}"


class S3Storage(StorageAdapter):
    """S3 / MinIO / OSS（S3 兼容 API）。

    boto3 延迟导入：没装boto3 时只有用到这个后端才会报错，
    本地开发完全不受影响。
    """

    name = "s3"

    def __init__(self) -> None:
        if not settings.s3_bucket:
            raise AssetError("S3_BUCKET 未配置")
        try:
            import boto3  # noqa: F401
        except ImportError as exc:
            raise AssetError("使用 S3 后端需安装 boto3：pip install boto3") from exc
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            kwargs: dict[str, Any] = {"region_name": settings.s3_region or None}
            if settings.s3_endpoint:
                kwargs["endpoint_url"] = settings.s3_endpoint
            if settings.s3_access_key:
                kwargs["aws_access_key_id"] = settings.s3_access_key
                kwargs["aws_secret_access_key"] = settings.s3_secret_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def write(self, key: str, data: bytes) -> str:
        extra: dict[str, Any] = {}
        if settings.s3_endpoint:      # MinIO / 部分 OSS 需要显式 content-type
            mime = _ext_of(key).lstrip(".")
            guessed, _ = mimetypes.guess_type(f"x.{mime}")
            if guessed:
                extra["ContentType"] = guessed
        self.client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, **extra)
        return self.url(key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=settings.s3_bucket, Key=key)
            return True
        except ClientError:
            return False

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> bool:
        self.client.delete_object(Bucket=settings.s3_bucket, Key=key)
        return True

    def size(self, key: str) -> int:
        return int(self.client.head_object(Bucket=settings.s3_bucket, Key=key)["ContentLength"])

    def url(self, key: str) -> str:
        base = (settings.s3_public_base or "").rstrip("/")
        if base:
            return f"{base}/{key}"
        if settings.s3_endpoint:
            return f"{settings.s3_endpoint.rstrip('/')}/{settings.s3_bucket}/{key}"
        return f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com/{key}"


_storage: StorageAdapter | None = None


def get_storage() -> StorageAdapter:
    global _storage
    if _storage is None:
        backend = (settings.asset_backend or "local").lower()
        _storage = S3Storage() if backend == "s3" else LocalStorage()
    return _storage


def reset_storage() -> None:
    """测试与配置热更新后调用。"""
    global _storage
    _storage = None


def svg_is_safe(data: bytes) -> bool:
    """SVG 可以内联脚本与外链，是投放场景的常见 XSS 载体，必须查。"""
    head = data[:8192].decode("utf-8", "ignore").lower()
    bad = ("<script", "javascript:", "onload=", "onclick=", "<foreignobject",
           "<iframe", "<embed", "<object", "data:text/html")
    return not any(b in head for b in bad)


_KEY_RE = re.compile(r"^asset/\d{4}-\d{2}/[a-f0-9]{16}\.[a-z0-9]{1,6}$")


def is_asset_key(value: str) -> bool:
    return bool(value and _KEY_RE.match(value))


def local_file_uri(key: str, storage: StorageAdapter | None = None) -> str | None:
    """仅 local 后端可用：返回可直接读盘的路径（导出内联用）。"""
    st = storage or get_storage()
    if not isinstance(st, LocalStorage):
        return None
    p = st._safe_path(key)
    return str(p) if p.is_file() else None


def copy_to_dir(key: str, dest: Path, storage: StorageAdapter | None = None) -> bool:
    """把资产复制到目标目录（bundle 打包用）。"""
    st = storage or get_storage()
    try:
        src = local_file_uri(key, st)
        if src:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            return True
        data = st.read(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception:
        return False