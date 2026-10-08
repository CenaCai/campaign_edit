"""资产 API：上传、列表、引用检查、删除、存储状态。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ...assets.service import (collect_asset_refs, delete_asset, get_asset,
                               list_assets, list_referencing_contents, save_asset)
from ...assets.storage import AssetError, get_storage
from ...config import settings
from ...db import get_db
from ...deps import get_current_user
from ...models import Content, User

router = APIRouter(prefix="/assets", tags=["assets"])


def _to_dict(row) -> dict[str, Any]:
    return {
        "id": row.id, "key": row.storage_key, "filename": row.filename,
        "mime": row.mime, "size": row.size, "width": row.width, "height": row.height,
        "url": row.url, "alt_text": row.alt_text, "tags": row.tags or [],
        "sha256": row.sha256[:16], "backend": row.storage_backend,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/status", summary="存储后端状态")
def storage_status(user: User = Depends(get_current_user)) -> dict[str, Any]:
    st = get_storage()
    info: dict[str, Any] = {
        "backend": st.name,
        "max_bytes": settings.asset_max_bytes,
        "allowed_mimes": [m.strip() for m in settings.asset_allowed_mimes.split(",")],
        "inline_threshold": settings.export_inline_assets_threshold,
    }
    if st.name == "local":
        info["root"] = str(st.root)
        info["url_prefix"] = f"{st.base_url}{st.url_prefix}"
    else:
        info["bucket"] = settings.s3_bucket
        info["region"] = settings.s3_region
        info["public_base"] = settings.s3_public_base or None
    info["usage_hint"] = {
        "email": "导出时建议 inline（邮件客户端不认相对路径）",
        "landing": "导出时建议 bundle（图片进 assets/，产物自包含）",
        "with_cdn": "有对象存储时选 cdn（替换为 CDN URL）",
    }
    return info


@router.post("", summary="上传资产（按内容哈希去重）")
async def upload(file: UploadFile = File(...), alt: str = Form(""),
                 tags: str = Form(""), project_id: str = Form(""),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict[str, Any]:
    data = await file.read()
    try:
        row = save_asset(
            db, data=data, filename=file.filename or "", mime=file.content_type or "",
            alt=alt, tags=[t.strip() for t in tags.split(",") if t.strip()],
            uploaded_by=user.id, project_id=project_id or None)
    except AssetError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _to_dict(row)


@router.get("", summary="资产列表")
def listing(project_id: str = None, mime: str = None, q: str = None,
            limit: int = Query(50, le=200), offset: int = 0,
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> dict[str, Any]:
    rows = list_assets(db, project_id=project_id, mime=mime, q=q, limit=limit, offset=offset)
    return {"items": [_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/{asset_id}", summary="资产详情")
def detail(asset_id: str, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = get_asset(db, asset_id)
    if row is None:
        raise HTTPException(404, "资产不存在")
    refs = list_referencing_contents(db, row.storage_key)
    return {**_to_dict(row), "referenced_by": refs, "reference_count": len(refs)}


@router.get("/{asset_id}/references", summary="谁在引用这个资产")
def references(asset_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = get_asset(db, asset_id)
    if row is None:
        raise HTTPException(404, "资产不存在")
    refs = list_referencing_contents(db, row.storage_key)
    return {"asset": _to_dict(row), "referenced_by": refs, "count": len(refs)}


@router.get("/{asset_id}/data", summary="读取图片内容（预览用）")
def raw(asset_id: str, db: Session = Depends(get_db),
        user: User = Depends(get_current_user)):
    from fastapi.responses import Response
    row = get_asset(db, asset_id)
    if row is None:
        raise HTTPException(404, "资产不存在")
    try:
        data = get_storage().read(row.storage_key)
    except AssetError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(data, media_type=row.mime,
                    headers={"Cache-Control": "public, max-age=31536000"})


@router.get("/{asset_id}/data.txt", summary="纯文本形式（调试/导出用）")
def raw_text(asset_id: str, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> dict[str, Any]:
    """给无法直接显示图片的场景（如某些 AI 工具）提供纯文本回退。"""
    row = get_asset(db, asset_id)
    if row is None:
        raise HTTPException(404, "资产不存在")
    try:
        data = get_storage().read(row.storage_key)
    except AssetError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"id": row.id, "mime": row.mime, "size": row.size,
            "data": data.decode("utf-8", "ignore")[:20000],
            "truncated": len(data) > 20000}


@router.delete("/{asset_id}", summary="删除资产（被引用时需 force）")
def remove(asset_id: str, force: bool = False, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> dict[str, Any]:
    try:
        res = delete_asset(db, asset_id, force=force)
    except AssetError as exc:
        raise HTTPException(404, str(exc)) from exc
    db.commit()
    if not res.get("ok"):
        raise HTTPException(409, res)
    return res


@router.get("/{asset_id}/html-snippet", summary="生成图片标签（插入编辑器用）")
def html_snippet(asset_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = get_asset(db, asset_id)
    if row is None:
        raise HTTPException(404, "资产不存在")
    alt = row.alt_text or row.filename or "image"
    w = f' width="{row.width}"' if row.width else ""
    h = f' height="{row.height}"' if row.height else ""
    return {
        "key": row.storage_key, "url": row.url,
        "img": f'<img src="{row.url}" alt="{alt}"{w}{h} loading="lazy">',
        "hint": "把这个 key 填到组件的 src 属性，而不是 URL——导出时才能被正确内联或打包。",
    }