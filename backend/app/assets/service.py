"""资产服务：入库、引用分析、导出时的内联与打包。

核心价值在于解决一个问题：**导出产物里的图片不能永远是编辑器临时地址**。
因此提供三种落地策略，导出时按需选择：

============  ======================================================
策略          适用场景
============  ======================================================
``inline``    邮件（邮件客户端不认相对路径，必须内联或绝对地址）
``bundle``    落地页/表单（图片进zip 的 assets/，产物自包含）
``cdn``       已有对象存储（上传后替换为 CDN URL）
============  ======================================================
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Asset
from .storage import (AssetError, build_key, check_allowed, get_storage, guess_mime,
                      image_size, is_asset_key, sniff_mime, svg_is_safe)

# schema 里可能承载图片/文件的 props 字段
_ASSET_PROPS = {"src", "image", "poster", "bg_image", "background_image",
                 "logo_image", "logo", "map_embed", "embed_url"}
_ASSET_ARRAY_FIELDS = ("items", "cards", "icons", "links", "steps", "faq")
# 这些是 iframe/视频嵌入，不当作静态资产处理
_EMBED_FIELDS = {"map_embed", "embed_url", "map_image"}


def save_asset(db: Session, *, data: bytes, filename: str, mime: str = "",
               alt: str = "", tags: list[str] | None = None,
               uploaded_by: str | None = None,
               project_id: str | None = None) -> Asset:
    """保存一个资产。按内容哈希去重：同一张图重复上传只存一份。"""
    if not data:
        raise AssetError("文件为空")
    # 魔数优先——不信客户端给的 MIME 与扩展名。
    # 两者都识别不出时抛 AssetError（→ 400），而不是走到后面某个字典取值报 500。
    final_mime = guess_mime(filename, mime, data)
    if not final_mime or not final_mime.startswith("image/"):
        shown = (data[:16].hex() or "空")
        raise AssetError(
            f"无法识别为图片（识别到 {final_mime or '未知类型'}，"
            f"文件头 {shown}）。仅支持 PNG / JPEG / GIF / WebP / AVIF / SVG。")
    check_allowed(final_mime, len(data), data)

    digest = hashlib.sha256(data).hexdigest()
    existing = db.execute(select(Asset).where(Asset.sha256 == digest)).scalar_one_or_none()
    key = build_key(filename, data)
    storage = get_storage()

    if existing is not None:
        # 同内容已存在：复用记录，只补一次存储（防止之前写失败）
        if not storage.exists(existing.storage_key):
            storage.write(existing.storage_key, data)
        if alt and not existing.alt_text:
            existing.alt_text = alt[:200]
        db.flush()
        return existing

    url = storage.write(key, data)
    dims = image_size(final_mime, data)
    row = Asset(
        key=key, storage_key=key, filename=(filename or key)[-160:],
        mime=final_mime, size=len(data), width=dims[0] if dims else None,
        height=dims[1] if dims else None, sha256=digest, url=url,
        storage_backend=storage.name, alt_text=alt[:200], tags=tags or [],
        project_id=project_id, uploaded_by=uploaded_by,
        is_svg_safe=(final_mime != "image/svg+xml" or svg_is_safe(data)),
    )
    db.add(row)
    db.flush()
    return row


def get_asset(db: Session, asset_id: str) -> Asset | None:
    return db.get(Asset, asset_id)


def get_by_key(db: Session, key: str) -> Asset | None:
    return db.execute(select(Asset).where(Asset.storage_key == key)).scalar_one_or_none()


def list_assets(db: Session, *, project_id: str | None = None,
                mime: str | None = None, q: str | None = None,
                limit: int = 50, offset: int = 0) -> list[Asset]:
    stmt = select(Asset)
    if project_id:
        stmt = stmt.where(Asset.project_id == project_id)
    if mime:
        stmt = stmt.where(Asset.mime == mime)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Asset.filename.like(like)) | (Asset.alt_text.like(like)))
    stmt = stmt.order_by(Asset.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


def delete_asset(db: Session, asset_id: str, *, force: bool = False) -> dict[str, Any]:
    """软删除。默认只下线引用，不动文件——资产可能正被多份内容引用。"""
    row = db.get(Asset, asset_id)
    if row is None:
        raise AssetError("资产不存在")
    refs = list_referencing_contents(db, row.storage_key)
    if refs and not force:
        return {"ok": False, "reason": "in_use", "referenced_by": refs,
                "message": f"该资产被 {len(refs)} 份内容引用，请先解除引用或使用 force"}
    storage = get_storage()
    if force:
        try:
            storage.delete(row.storage_key)
        except Exception as exc:
            return {"ok": False, "reason": "storage_error", "message": str(exc)}
    row.is_active = False
    row.deleted_at = datetime_now()
    db.flush()
    return {"ok": True, "purged": force}


def datetime_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 引用分析

def collect_asset_refs(schema: dict) -> list[str]:
    """从 schema 中找出所有引用的资产 key（asset/... 形式的本地资产）。"""
    refs: list[str] = []

    def walk(node: dict) -> None:
        props = node.get("props") or {}
        for key in _ASSET_PROPS:
            if key in _EMBED_FIELDS:
                continue
            v = props.get(key)
            if isinstance(v, str) and is_asset_key(v):
                refs.append(v)
        # 数组字段里嵌套对象（票档卡、FAQ 等）
        for arr_field in _ASSET_ARRAY_FIELDS:
            arr = props.get(arr_field)
            if not isinstance(arr, list):
                continue
            for item in arr:
                if isinstance(item, dict):
                    for key, v in item.items():
                        if key in _EMBED_FIELDS:
                            continue
                        if isinstance(v, str) and is_asset_key(v):
                            refs.append(v)
        for ch in node.get("children") or []:
            if isinstance(ch, dict):
                walk(ch)

    root = schema.get("root") or {}
    walk(root)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def list_referencing_contents(db: Session, storage_key: str) -> list[dict[str, Any]]:
    """找出哪些内容引用了某资产（删除前检查用）。"""
    from ..models import Content

    out: list[dict[str, Any]] = []
    rows = db.execute(select(Content)).scalars()
    for c in rows:
        if not c.current_version_id:
            continue
        v = db.get(_version_model(), c.current_version_id)
        if not v or not v.schema:
            continue
        if storage_key in collect_asset_refs(v.schema):
            out.append({"id": c.id, "key": c.key, "name": c.name, "status": c.status})
    return out


def _version_model():
    from ..models import ContentVersion
    return ContentVersion


def validate_assets(db: Session, schema: dict) -> dict[str, Any]:
    """导出前的资产校验：本地资产是否还存在，图片是否缺 alt。"""
    refs = collect_asset_refs(schema)
    storage = get_storage()
    missing: list[str] = []
    no_alt: list[dict[str, str]] = []
    resolved: dict[str, str] = {}

    def walk(node: dict) -> None:
        props = node.get("props") or {}
        for key in _ASSET_PROPS:
            if key in _EMBED_FIELDS:
                continue
            v = props.get(key)
            if isinstance(v, str) and is_asset_key(v) and not props.get("alt"):
                no_alt.append({"node_id": node.get("id", ""), "prop": key, "key": v})
        for ch in node.get("children") or []:
            if isinstance(ch, dict):
                walk(ch)

    walk(schema.get("root") or {})

    for key in refs:
        row = get_by_key(db, key)
        if row is not None and row.is_active:
            resolved[key] = row.url
            continue
        if storage.exists(key):
            resolved[key] = storage.url(key)
        else:
            missing.append(key)

    return {
        "ok": not missing,
        "referenced": refs,
        "count": len(refs),
        "missing": missing,
        "no_alt": no_alt,
        "urls": resolved,
        "error_count": len(missing),
        "warn_count": len(no_alt),
    }


# ---------------------------------------------------------------- 导出集成

def _data_uri(key: str, mime: str) -> str | None:
    try:
        data = get_storage().read(key)
    except Exception:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def inline_assets_in_schema(schema: dict, db: Session, *, threshold: int | None = None
                            ) -> tuple[dict, dict[str, Any]]:
    """把 schema 里的本地资产替换为 data URI。

    仅替换小于阈值的图片——邮件客户端通常对 data URI 有 2~3MB 限制，
    更大的图片应改用 CDN。
    """
    limit = threshold if threshold is not None else settings.export_inline_assets_threshold
    storage = get_storage()
    out = json.loads(json.dumps(schema))  # 深拷贝
    stats = {"inlined": [], "skipped_large": [], "missing": []}

    def repl(node: dict) -> None:
        props = node.get("props") or {}
        for key in list(props.keys()):
            if key in _EMBED_FIELDS:
                continue
            v = props.get(key)
            if not (isinstance(v, str) and is_asset_key(v)):
                continue
            row = get_by_key(db, v)
            size = row.size if row else None
            if size is None:
                try:
                    size = storage.size(v)
                except Exception:
                    size = None
            if size is not None and size > limit:
                stats["skipped_large"].append(v)
                # 大图改用绝对地址（邮件客户端支持）
                props[key] = row.url if row else storage.url(v)
                continue
            uri = _data_uri(v, row.mime if row else "image/png")
            if uri:
                props[key] = uri
                stats["inlined"].append(v)
            else:
                stats["missing"].append(v)
        for ch in node.get("children") or []:
            if isinstance(ch, dict):
                repl(ch)

    repl(out.get("root") or {})
    return out, stats


def bundle_assets(db: Session, schema: dict, dest_dir: Path) -> dict[str, Any]:
    """把引用的本地资产复制进产物目录 assets/，并把 schema 里的key 改成相对路径。

    产物因此是自包含的：解压后 index.html + assets/ 可直接部署。
    """
    from .storage import copy_to_dir

    refs = collect_asset_refs(schema)
    copied: list[str] = []
    failed: list[str] = []
    mapping: dict[str, str] = {}

    for key in refs:
        name = Path(key).name
        target = dest_dir / "assets" / name
        if copy_to_dir(key, target):
            copied.append(key)
            mapping[key] = f"assets/{name}"
        else:
            failed.append(key)

    out = json.loads(json.dumps(schema))

    def repl(node: dict) -> None:
        props = node.get("props") or {}
        for pk, v in list(props.items()):
            if isinstance(v, str) and v in mapping:
                props[pk] = mapping[v]
        for ch in node.get("children") or []:
            if isinstance(ch, dict):
                repl(ch)

    repl(out.get("root") or {})
    return {"schema": out, "copied": copied, "failed": failed,
            "total": len(refs)}


def asset_url_for(key: str, db: Session) -> str:
    """取资产的最终访问 URL（优先 DB 记录，其次存储后端实时解析）。"""
    row = get_by_key(db, key)
    if row is not None and row.url:
        return row.url
    return get_storage().url(key)