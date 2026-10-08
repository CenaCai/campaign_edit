"""Mautic 7 API 投递器（零 SDK，标准库 + SSL）。

已规避的生产环境坑（来自真实故障复盘）：
1. **PUT 必须传完整对象**：Mautic 7 API Platform 对 partial payload 调jms_serializer
   会 500。``update_*`` 一律先 GET 全量再合并 PUT。
2. **路由是 /api/v2**（部分端点仍在 /api），下面按端点做fallback。
3. **landing 页跳转**：``customHtml`` 里的 meta-refresh/JS 才是真实生效的跳转方式，
   ``redirectType``/``redirectUrl`` 会被构建逻辑忽略 —— 所以这里一律写 customHtml。
4. **软下线**：不提供 DELETE，只提供 ``isPublished=false``（PATCH /emails/{id}/publish
   之类走 deactivate 端点），避免误删资产。
5. **表单字段映射**：Mautic form 的 fieldName 必须唯一且不能与保留字冲突。
"""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..models import ContentKind
from ..render import render, resolve_tokens

# Mautic 保留字段名（form fieldName 冲突会静默丢数据）
MAUTIC_RESERVED_FIELDS = {
    "id", "form", "lead", "ip", "date", "landing_page", "url", "title", "description",
    "name", "email", "firstname", "lastname", "company", "phone", "country", "city",
    "postcode", "address", "message", "consent", "locale", "timezone",
}


@dataclass
class MauticResult:
    ok: bool
    action: str = ""
    asset_id: int | None = None
    asset_type: str = ""
    url: str = ""
    error: str = ""
    payload: dict | None = None
    warnings: list[str] | None = None


class MauticClient:
    def __init__(self, base_url: str | None = None, username: str | None = None,
                 password: str | None = None) -> None:
        self.base = (base_url or settings.mautic_base_url).rstrip("/")
        self.user = username or settings.mautic_username
        self.pwd = password or settings.mautic_password
        token = base64.b64encode(f"{self.user}:{self.pwd}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # -------------------------------------------------- HTTP
    def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, Any]:
        if not self.base:
            raise RuntimeError("MAUTIC_BASE_URL 未配置")
        url = f"{self.base}{path}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=body, method=method.upper())
        for k, v in self.headers.items():
            req.add_header(k, v)
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=40, context=ctx) as resp:
                raw = resp.read().decode("utf-8", "ignore")
                try:
                    return resp.status, json.loads(raw)
                except Exception:
                    return resp.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw[:1500]
        except urllib.error.URLError as e:
            raise RuntimeError(f"Mautic 不可达: {e}") from e

    def get(self, path: str) -> tuple[int, Any]:
        return self._request("GET", path)

    def post(self, path: str, payload: dict) -> tuple[int, Any]:
        return self._request("POST", path, payload)

    def put(self, path: str, payload: dict) -> tuple[int, Any]:
        return self._request("PUT", path, payload)

    def patch(self, path: str, payload: dict) -> tuple[int, Any]:
        return self._request("PATCH", path, payload)

    def api2(self, path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, Any]:
        """优先 /api/v2，失败回退 /api。"""
        code, data = self._request(method, f"/api/v2{path}", payload)
        if code == 404:
            return self._request(method, f"/api{path}", payload)
        return code, data

    def fetch_full(self, path: str) -> dict[str, Any]:
        code, data = self.get(path)
        if code != 200 or not isinstance(data, dict):
            raise RuntimeError(f"GET {path} 失败: {code} {str(data)[:200]}")
        return data

    # -------------------------------------------------- 探测
    def ping(self) -> dict[str, Any]:
        try:
            code, data = self.get("/api/system/info")
            if code == 200 and isinstance(data, dict):
                return {"ok": True, "version": data.get("version"),
                        "edition": data.get("edition"), "url": self.base}
            return {"ok": False, "error": f"HTTP {code}", "url": self.base}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "url": self.base}


# ---------------------------------------------------------------- 字段映射

def map_form_fields(fields: list[dict]) -> tuple[list[dict], list[str]]:
    """Block Schema 字段 → Mautic form fieldHtml/fieldName。映射 + 告警。"""
    html_parts: list[dict] = []
    warnings: list[str] = []
    used: set[str] = set()
    for f in fields:
        if f.get("input_type") == "hidden" and f["name"] not in (
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
            continue
        target = str(f.get("mautic_field") or f["name"])
        safe = "".join(ch for ch in target if ch.isalnum() or ch in "_") or "field"
        if safe in MAUTIC_RESERVED_FIELDS and f.get("mautic_field"):
            safe = f"custom_{safe}"
            warnings.append(f"字段 {f['name']} 映射到 Mautic 保留字，已重命名为 {safe}")
        base = safe
        i = 2
        while safe in used:
            safe = f"{base}_{i}"
            i += 1
        if safe != target:
            warnings.append(f"字段 {f['name']} 重命名为 {safe} 以避免冲突")
        used.add(safe)

        label = f.get("label") or safe
        req = "required" if f.get("required") else ""
        itype = f.get("input_type", "text")
        if f.get("consent"):
            html = (f'<label><input type="checkbox" name="{safe}" value="1" {req}> '
                    f'<span>{label}</span></label>')
        elif itype == "textarea":
            html = (f'<label>{label}<textarea name="{safe}" {req}></textarea></label>')
        elif itype == "select":
            opts = "".join(f'<option value="{o.get("value")}">{o.get("label")}</option>'
                           for o in f.get("options", []))
            html = f'<label>{label}<select name="{safe}" {req}><option value="">--</option>{opts}</select></label>'
        elif itype in ("radio", "checkbox"):
            opts = "".join(f'<label><input type="{itype}" name="{safe}" value="{o.get("value")}">'
                           f'<span>{o.get("label")}</span></label>'
                           for o in f.get("options", []))
            html = f'<div class="ce-field"><label>{label}</label>{opts}</div>'
        else:
            html = (f'<label>{label}<input type="{itype}" name="{safe}" {req} '
                    f'placeholder="{f.get("placeholder", "")}"></label>')
        html_parts.append({"fieldName": safe, "label": label, "type": itype, "required": bool(f.get("required"))})
        _ = html
    return html_parts, warnings


def _hidden_inputs(fields: list[dict]) -> str:
    return "".join(
        f'<input type="hidden" name="{k}" value="">'
        for k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
    )


# ---------------------------------------------------------------- 推送

def push_email(client: MauticClient, schema: dict, *, name: str, publish: bool = False,
               update_id: int | None = None) -> MauticResult:
    doc = schema.get("doc") or {}
    html = render(schema, kind=ContentKind.EMAIL, tokens=resolve_tokens(schema))
    subject = (doc.get("subject") or name).strip()

    if update_id:
        #坑 1：先 GET 全量，再合并 PUT
        try:
            existing = client.fetch_full(f"/api/emails/{update_id}")
        except Exception as exc:
            return MauticResult(False, "update_email", error=f"读取现有邮件失败: {exc}")
        payload = {**existing, "name": name, "subject": subject,
                   "customHtml": html, "isPublished": bool(publish)}
        code, data = client.put(f"/api/emails/{update_id}", payload)
        if code not in (200, 201):
            return MauticResult(False, "update_email", error=f"HTTP {code}: {str(data)[:400]}")
        asset_id = data.get("id", update_id)
        return MauticResult(True, "update_email", asset_id, "email",
                            f"/api/emails/{asset_id}", payload={"id": asset_id})

    payload = {
        "name": name, "subject": subject, "customHtml": html,
        "isPublished": bool(publish), "isPublishedUpNow": False,
    }
    code, data = client.post("/api/emails/new", payload)
    if code not in (200, 201):
        code, data = client.post("/api/emails", payload)
    if code not in (200, 201):
        return MauticResult(False, "create_email", error=f"HTTP {code}: {str(data)[:400]}")
    asset_id = data.get("id")
    return MauticResult(True, "create_email", asset_id, "email",
                        f"/api/emails/{asset_id}", payload={"id": asset_id})


def push_form(client: MauticClient, schema: dict, *, name: str, publish: bool = False,
              campaign_id: int | None = None) -> MauticResult:
    from ..render.form import FormRenderer
    fields = FormRenderer().collect_fields(schema.get("root") or {})
    mapped, warnings = map_form_fields(fields)
    if not mapped:
        return MauticResult(False, "create_form", error="表单没有可映射的字段")

    doc = schema.get("doc") or {}
    rendered = render(schema, kind=ContentKind.FORM, tokens=resolve_tokens(schema),
                      standalone=True)
    body = rendered.split("<body>", 1)[-1].split("</body>", 1)[0].strip()
    mautic_tpl = _strip_ce_form_shell(body)

    payload: dict[str, Any] = {
        "name": name,
        "description": doc.get("description") or name,
        "isPublished": bool(publish),
        "isSaveCopy": False,
        "inlineOnSuccess": False,
        "postableHtml": mautic_tpl,
        "formTemplate": "campaign-edit",
        "fields": mapped,
        "style": "",
    }
    if campaign_id:
        payload["campaign"] = campaign_id
    code, data = client.post("/api/forms/new", payload)
    if code not in (200, 201):
        code, data = client.api2("/forms/new", "POST", payload)
    if code not in (200, 201):
        return MauticResult(False, "create_form", error=f"HTTP {code}: {str(data)[:400]}")
    asset_id = data.get("id")
    return MauticResult(True, "create_form", asset_id, "form", f"/api/forms/{asset_id}",
                        payload={"id": asset_id, "fields": len(mapped)}, warnings=warnings)


def push_page(client: MauticClient, schema: dict, *, name: str, publish: bool = False,
              alias: str = "", redirect_url: str = "") -> MauticResult:
    doc = schema.get("doc") or {}
    html = render(schema, kind=ContentKind.LANDING, tokens=resolve_tokens(schema))
    # 坑 3：跳转靠 customHtml 内的 meta-refresh + JS，不依赖 redirectType
    if redirect_url:
        html = _inject_redirect(html, redirect_url)
    payload = {
        "title": name,
        "alias": alias or _alias(name),
        "customHtml": html,
        "isPublished": bool(publish),
        # 保留 Mautic 自己的字段（路由/SEO/主题），这样在 Mautic 后台仍可编辑
        "template": "campaign-edit",
        "description": doc.get("description") or "",
    }
    code, data = client.post("/api/pages/new", payload)
    if code not in (200, 201):
        return MauticResult(False, "create_page", error=f"HTTP {code}: {str(data)[:400]}")
    asset_id = data.get("id")
    return MauticResult(True, "create_page", asset_id, "page", f"/api/pages/{asset_id}",
                        payload={"id": asset_id, "url": f"{client.base}/{payload['alias']}"})


def push_content(client: MauticClient, schema: dict, *, name: str, publish: bool = False,
                 update_id: int | None = None, redirect_url: str = "",
                 campaign_id: int | None = None) -> MauticResult:
    kind = schema.get("kind")
    if kind == ContentKind.EMAIL:
        return push_email(client, schema, name=name, publish=publish, update_id=update_id)
    if kind == ContentKind.FORM:
        return push_form(client, schema, name=name, publish=publish, campaign_id=campaign_id)
    if kind == ContentKind.LANDING:
        return push_page(client, schema, name=name, publish=publish, redirect_url=redirect_url)
    return MauticResult(False, "push", error=f"不支持的 kind: {kind}")


def set_published(client: MauticClient, asset_type: str, asset_id: int, published: bool) -> MauticResult:
    """软上下线（不 DELETE）。Mautic 的 publish/draft 端点按资源类型区分。"""
    plural = {"email": "emails", "form": "forms", "page": "pages"}.get(asset_type)
    if not plural:
        return MauticResult(False, "set_published", error=f"未知资产类型 {asset_type}")
    action = "publish" if published else "unpublish"
    code, data = client.api2(f"/{plural}/{asset_id}/{action}", "PUT")
    if code not in (200, 201, 204):
        return MauticResult(False, action, error=f"HTTP {code}: {str(data)[:300]}")
    return MauticResult(True, action, asset_id, asset_type, f"/api/{plural}/{asset_id}",
                        payload={"isPublished": published})


def _alias(name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (name or "page").lower()).strip("-")
    return (s or "campaign-page")[:80]


def _inject_redirect(html: str, url: str) -> str:
    """在 </head> 前插入 meta-refresh + JS 跳转 —— Mautic 上真正生效的方式。"""
    import re
    tag = (f'<meta http-equiv="refresh" content="0;url={url}">'
           f'<script>setTimeout(function(){{window.location.replace({json.dumps(url)})}},0);</script>')
    if "</head>" in html:
        return html.replace("</head>", f"{tag}</head>", 1)
    return tag + html


def _strip_ce_form_shell(body: str) -> str:
    """剥掉 Campaign Edit 的页面外壳，只留表单本体（Mautic 自带模板容器）。"""
    import re
    out = re.sub(r"<main[^>]*>(.*?)</main>", r"\1", body, flags=re.S | re.I)
    out = re.sub(r'<script id="ce-form-rules"[^>]*>.*?</script>', "", out, flags=re.S | re.I)
    out = re.sub(r"<script>.*?</script>", "", out, flags=re.S | re.I)
    # Mautic 自己会注入 utm hidden，只需保留我们声明的
    return out.strip()


def discover_assets(client: MauticClient, keyword: str = "", limit: int = 50) -> dict[str, Any]:
    """按关键字列出已有资产（对接前先查重，避免重复创建）。"""
    out: dict[str, Any] = {}
    filters = f"?search={urllib.parse.quote(keyword)}&limit={limit}&orderBy=id&orderByDir=desc" if keyword \
        else f"?limit={limit}&orderBy=id&orderByDir=desc"
    for key, path, field in (("emails", "/api/emails", "subject"),
                             ("forms", "/api/forms", "name"),
                             ("pages", "/api/pages", "title")):
        try:
            code, data = client.get(path + filters)
            total = data.get("total", 0) if isinstance(data, dict) else 0
            items = (data.get(f"{key}") or []) if isinstance(data, dict) else []
            out[key] = {
                "total": total,
                "items": [{"id": i.get("id"), "name": i.get(field) or i.get("name") or i.get("title"),
                           "isPublished": i.get("isPublished"), "alias": i.get("alias")}
                          for i in items[:limit]],
            }
        except Exception as exc:
            out[key] = {"error": str(exc)}
    return out


def maulic_config_status() -> dict[str, Any]:
    return {
        "configured": settings.mautic_configured,
        "base_url": settings.mautic_base_url or None,
        "username": settings.mautic_username or None,
        "enabled": settings.mautic_api_enabled,
    }