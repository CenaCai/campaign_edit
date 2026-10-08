"""追踪注入与表单标准JSON Schema。

两件事：

1. **追踪注入** —— 运营在 schema 里填``tracking: {utm_source: "email", ...}``，
   导出时把参数拼到所有链接上。做成"配置驱动"而不是"写死在代码里"，
   这样不同渠道的追踪需求不需要改代码。

2. **表单 JSON Schema** —— 现有 ``collect_fields()`` 是内部模型，
   但生态里 Formily / ajv / 文档生成器都认JSON Schema。
   同时输出 draft-07 格式与 Formily 的 uiSchema，可直接被外部工具消费。
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..render.common import with_utm
from ..render.form import FormRenderer

_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
             "utm_id", "utm_source_platform")

# 把 Jinja/Handlebars 占位转成 JS 字符串里的安全写法
_JS_ESCAPE = re.compile(r"[^A-Za-z0-9_]")


# ---------------------------------------------------------------- 追踪

def normalize_tracking(tracking: dict | None) -> dict[str, str]:
    """规整 tracking 配置，只保留已知的 UTM 键。"""
    if not isinstance(tracking, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in tracking.items():
        if k in _UTM_KEYS and v not in (None, ""):
            out[k] = str(v)[:120]
    return out


def utm_query(tracking: dict | None) -> str:
    t = normalize_tracking(tracking)
    return "&".join(f"{k}={v}" for k, v in t.items()) if t else ""


def inject_tracking(schema: dict) -> tuple[dict, dict[str, Any]]:
    """把 tracking 配置写进所有链接的 href。

    做在 **schema 层**（改 props.url），而不是渲染后的 HTML ——
    这样预览、导出、Mautic 投递三条链路自动一致。
    """
    work = json.loads(json.dumps(schema))
    tracking = normalize_tracking((work.get("tracking") or work.get("doc", {}).get("tracking")))
    if not tracking:
        return work, {"applied": 0, "utm": {}}

    utm = "&".join(f"{k}={v}" for k, v in tracking.items())
    n = 0

    def walk(node: dict) -> None:
        nonlocal n
        props = node.get("props") or {}
        for key in ("url", "href", "link", "logo", "src"):
            v = props.get(key)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                # 已有同名参数则不重复追加
                if not re.search(rf"[?&]{re.escape(key.split('?')[0])}=", v):
                    props[key] = with_utm(v, utm)
                    n += 1
        for arr in props.values():
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict):
                        for k, v in list(item.items()):
                            if isinstance(v, str) and v.startswith(("http://", "https://")):
                                item[k] = with_utm(v, utm)
                                n += 1
        for ch in node.get("children") or []:
            if isinstance(ch, dict):
                walk(ch)

    walk(work.get("root") or {})
    return work, {"applied": n, "utm": tracking, "query": utm}


def inject_tracking_js(html: str, tracking: dict | None) -> str:
    """给落地页注入读取 UTM 并回填隐藏域的脚本。

    表单 renderer 已有回填逻辑，这里额外做一层：把首次访问的来源存入
    sessionStorage，跨越"落地页 → 二次访问 → 转化页"时仍能归因。
    """
    t = normalize_tracking(tracking)
    if not t:
        return html
    config = json.dumps(t, ensure_ascii=False)
    script = f"""
<script>
(function(){{
  var utm = {config};
  try {{
    var qs = new URLSearchParams(location.search);
    var found = {{}};
    Object.keys(utm).forEach(function(k){{
      var v = qs.get(k);
      if (v) {{ found[k] = v; sessionStorage.setItem('utm_'+k, v); }}
      else if (sessionStorage.getItem('utm_'+k)) {{ found[k] = sessionStorage.getItem('utm_'+k); }}
    }});
    Object.keys(found).forEach(function(k){{
      document.querySelectorAll('[data-ce-utm="'+k+'"]').forEach(function(el){{ el.value = found[k]; }});
    }});
    if (window.dataLayer) {{ window.dataLayer.push({{event:'ce_utm_capture', utm: found}}); }}
  }} catch (e) {{}}
  try {{ document.querySelectorAll('[data-track]').forEach(function(el){{
    var a = el.getAttribute('href') || '';
    if (a.indexOf('http') !== 0) return;
    var sep = a.indexOf('?') >= 0 ? '&' : '?';
    var q = Object.keys(utm).map(function(k){{ return k+'='+encodeURIComponent(utm[k]); }}).join('&');
    if (q && a.indexOf('utm_source') < 0) el.setAttribute('href', a + sep + q);
  }}); }} catch (e2) {{}}
}})();
</script>"""
    if "</body>" in html:
        return html.replace("</body>", script + "\n</body>", 1)
    return html + script


# ---------------------------------------------------------------- 表单 JSON Schema

_LABEL_TO_ENUM = {
    "国家": "country", "票种": "choice", "场次": "choice", "感兴趣": "choice",
    "语言": "locale", "票档": "choice", "人数": "number",
}


def to_json_schema(schema: dict, *, title: str = "表单") -> dict[str, Any]:
    """Block Schema → draft-07 JSON Schema。

    可直接被 ajv 校验、被 Formily 消费、被文档工具生成说明。
    """
    fields = FormRenderer().collect_fields(schema.get("root") or {})
    props: dict[str, Any] = {}
    required: list[str] = []
    seen_names: set[str] = set()

    for f in fields:
        name = f["name"]
        # 同名字段（多实例化内容后可能重复）只保留第一个，避免 JSON Schema 出现重复 required
        if name in seen_names:
            continue
        seen_names.add(name)
        p: dict[str, Any] = {"title": f.get("label") or name}
        rules = f.get("rules") or {}
        itype = f["input_type"]

        if f.get("consent"):
            p.update({"type": "boolean", "const": True,
                      "description": f.get("consent_text") or "需同意条款"})
        elif f["type"] == "form.select_field":
            opts = [o.get("value") for o in f.get("options", []) if o.get("value")]
            p.update({"type": "string", "enum": opts})
            if rules.get("enum"):
                p["enum"] = rules["enum"]
        elif f["type"] == "form.radio_field":
            p.update({"type": "string",
                      "enum": [o.get("value") for o in f.get("options", []) if o.get("value")]})
        elif f["type"] == "form.checkbox_field" and len(f.get("options", [])) > 1:
            p.update({"type": "array", "items": {
                "type": "string",
                "enum": [o.get("value") for o in f["options"] if o.get("value")]}})
        elif itype == "number":
            p["type"] = "number"
            if rules.get("min") is not None:
                p["minimum"] = rules["min"]
            if rules.get("max") is not None:
                p["maximum"] = rules["max"]
        elif itype == "email":
            p.update({"type": "string", "format": "email"})
        elif itype == "date":
            p["type"] = "string"
            p["format"] = "date"
            if rules.get("min"):
                p["minimum"] = str(rules["min"])
            if rules.get("max"):
                p["maximum"] = str(rules["max"])
        elif itype == "textarea":
            p["type"] = "string"
            if rules.get("maxLength"):
                p["maxLength"] = rules["maxLength"]
        else:
            p["type"] = "string"
            if rules.get("minLength"):
                p["minLength"] = rules["minLength"]
            if rules.get("maxLength"):
                p["maxLength"] = rules["maxLength"]
            if rules.get("pattern"):
                p["pattern"] = rules["pattern"]

        if f.get("placeholder"):
            p["description"] = f["placeholder"]
        if f.get("help_text"):
            p["x-help"] = f["help_text"]
        if f.get("default"):
            p["default"] = f["default"]
        if name in ("utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "ce_website", "ce_hp"):
            p["x-hidden"] = True
        if f.get("mautic_field"):
            p["x-mautic-field"] = f["mautic_field"]

        props[name] = p
        if f.get("required"):
            required.append(name)

    root_props = (schema.get("root") or {}).get("props") or {}
    out: dict[str, Any] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": title or (schema.get("doc") or {}).get("name") or "表单",
        "type": "object",
        "properties": props,
    }
    if required:
        out["required"] = required
    extra = {k: root_props.get(k) for k in ("form_name", "submit_label",
                                            "success_message", "action", "method")
             if root_props.get(k) not in (None, "")}
    if extra:
        out["x-form"] = extra
    return out


def to_ui_schema(schema: dict) -> dict[str, Any]:
    """生成 Formily uiSchema（布局与分组信息）。"""
    fields = FormRenderer().collect_fields(schema.get("root") or {})
    props: dict[str, Any] = {}
    groups: list[str] = []

    def scan(node: dict, current: str) -> str:
        for ch in node.get("children") or []:
            ntype = ch.get("type", "")
            if ntype == "form.section":
                # 空 title 不生成 "分组1" 这类占位名——对消费方毫无信息量
                g = (ch.get("props") or {}).get("title") or ""
                g = g.strip() if isinstance(g, str) else ""
                if g and g not in groups:
                    groups.append(g)
                scan(ch, g)
            elif (ntype.startswith("form.") and "_field" in ntype) \
                    or ntype == "form.consent_field":
                f = next((x for x in fields if x["node_id"] == ch.get("id")), None)
                if f:
                    ui: dict[str, Any] = {
                        "title": f["label"],
                        "x-component": "Input" if f["input_type"] not in (
                            "select", "radio", "checkbox", "textarea") else {
                            "select": "Select", "radio": "RadioGroup",
                            "checkbox": "CheckboxGroup", "textarea": "Input.TextArea",
                        }[f["input_type"]],
                    }
                    if f.get("placeholder"):
                        ui["x-placeholder"] = f["placeholder"]
                    if f.get("help_text"):
                        ui["x-help"] = f["help_text"]
                    if f["input_type"] == "select" or f["type"] == "form.radio_field":
                        ui["x-options"] = [
                            {"label": o.get("label"), "value": o.get("value")}
                            for o in f.get("options", [])]
                    if f.get("width") == "half":
                        ui["x-decorator-props"] = {"style": {"width": "50%"}}
                    props[f["name"]] = ui
                    if current and current not in groups:
                        groups.append(current)
            elif ch.get("container"):
                scan(ch, current)
        return current

    scan(schema.get("root") or {}, "")
    out: dict[str, Any] = {"x-component": "Form", "properties": props}
    if groups:
        # 分组信息供消费方（如自定义表单设计器）决定分步渲染；
        # 标准 uiSchema 不支持分组，这里用 x-groups 扩展键承载。
        out["x-groups"] = groups
    return out


def to_ajv_errors(jsonschema_doc: dict, payload: dict) -> list[str]:
    """轻量必填校验（不引 ajv）。给前端与服务端共用。"""
    errs: list[str] = []
    props = jsonschema_doc.get("properties") or {}
    for name in jsonschema_doc.get("required") or []:
        v = payload.get(name)
        if v in (None, "", [], {}):
            errs.append(f"{props.get(name, {}).get('title', name)} 为必填")
    for name, spec in props.items():
        v = payload.get(name)
        if v in (None, ""):
            continue
        if spec.get("type") == "string" and spec.get("enum") and v not in spec["enum"]:
            errs.append(f"{spec.get('title', name)} 取值不在允许范围内")
        if spec.get("type") == "string" and spec.get("format") == "email":
            if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$", str(v)):
                errs.append(f"{spec.get('title', name)} 邮箱格式不正确")
        if spec.get("maxLength") and isinstance(v, str) and len(v) > spec["maxLength"]:
            errs.append(f"{spec.get('title', name)} 超过 {spec['maxLength']} 字符")
    return errs