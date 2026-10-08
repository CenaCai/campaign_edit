"""表单渲染器：Block Schema → 可直接落地的 HTML + JS（零依赖）。

产物包含三件套：
  1. 语义化 HTML（带label/aria/required/fieldset）
  2. 独立 JS（前端校验 + AJAX 提交 + 埋点），无第三方库
  3. 一份 ``fields`` 字段清单（供 CRM / Mautic / 数据层消费）

校验规则从组件 props 推导：required / pattern / min-max / email / phone，
phone 用按country_code 的正则表（含 UK 国际区号格式）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from .common import esc, slugify, style_str
from .theme import merge_tokens

PHONE_PATTERNS = {
    "UK": r"^\+?44?\s?\d{9,10}$|^\(?0\d{2,4}\)?[\s-]?\d{6,8}$",
    "US": r"^\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$",
    "CN": r"^1[3-9]\d{9}$|^\+?861[3-9]\d{9}$",
}

INPUT_TYPE = {
    "form.text_field": "text",
    "form.email_field": "email",
    "form.phone_field": "tel",
    "form.number_field": "number",
    "form.date_field": "date",
    "form.textarea_field": "textarea",
    "form.select_field": "select",
    "form.radio_field": "radio",
    "form.checkbox_field": "checkbox",
    "form.hidden_field": "hidden",
    "form.consent_field": "checkbox",
}


def _t(tokens: dict, key: str) -> str:
    return str(tokens.get(key, ""))


class FormRenderer:
    kind = "form"

    def __init__(self, tokens: dict[str, None] | dict | None = None) -> None:
        self.t = merge_tokens(tokens)

    # -------------------------------------------------- 主入口
    def render(self, schema: dict, *, with_js: bool = True, ajax: bool | None = None,
               standalone: bool = True) -> str:
        root = schema.get("root") or {}
        doc = schema.get("doc") or {}
        p = root.get("props") or {}
        fields = self.collect_fields(root)
        form_id = f"ce-form-{slugify(doc.get('name') or 'form', 'form')}"

        if standalone:
            return self._standalone(schema, fields, form_id, with_js, ajax)
        body = self._form_inner(schema, fields, form_id, ajax)
        return body

    # -------------------------------------------------- 字段收集
    def collect_fields(self, root: dict) -> list[dict[str, Any]]:
        """输出统一字段模型：前端渲染 / 校验 / Mautic 映射三处共用。"""
        out: list[dict[str, Any]] = []

        def walk(node: dict) -> None:
            for ch in node.get("children") or []:
                ntype = ch.get("type", "")
                if ntype.startswith("form.section") or ntype == "form.root":
                    walk(ch)
                    continue
                if ntype in INPUT_TYPE or ntype == "form.captcha":
                    out.append(self._field_model(ch))
                else:
                    walk(ch)

        walk(root)
        return out

    def _field_model(self, node: dict) -> dict[str, Any]:
        p = node.get("props") or {}
        ntype = node.get("type")
        # name 缺失时的兜底链：name → label 派生 → 节点 id。
        # 不能直接用节点 id：那会让同一模板实例化两次得到不同字段名，
        # 导致已入库的数据对不上（这正是 JSON Schema 里出现重复 required 的原因）。
        name = (p.get("name") or "").strip()
        if not name:
            # 中文标签保留（正则只剥标点），这样运营在 CRM 里看到的是
            # field_隐私政策 而不是 field_b861a5ff05 —— 后者没有任何可读性
            raw = str(p.get("label") or node.get("id") or "field").strip()
            label = re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "_", raw).strip("_").lower()
            name = f"field_{label}" if label else "field"
        rules: dict[str, Any] = {}
        if p.get("required"):
            rules["required"] = True
        if p.get("pattern"):
            rules["pattern"] = p["pattern"]
        if p.get("min_length"):
            rules["minLength"] = int(p["min_length"])
        if p.get("max_length"):
            rules["maxLength"] = int(p["max_length"])
        if ntype == "form.email_field":
            rules["type"] = "email"
        if ntype == "form.number_field":
            rules["type"] = "number"
            if p.get("min"):
                rules["min"] = p["min"]
            if p.get("max"):
                rules["max"] = p["max"]
        if ntype == "form.phone_field" and p.get("validate_pattern", True):
            cc = str(p.get("country_code") or "UK").upper()
            rules["pattern"] = PHONE_PATTERNS.get(cc, PHONE_PATTERNS["UK"])
            rules["phoneCountry"] = cc
        if ntype == "form.date_field":
            if p.get("min_date"):
                rules["min"] = p["min_date"]
            if p.get("max_date"):
                rules["max"] = p["max_date"]
        if ntype in ("form.select_field", "form.radio_field", "form.checkbox_field"):
            rules["enum"] = [o.get("value") for o in (p.get("options") or []) if isinstance(o, dict)]

        return {
            "node_id": node.get("id"),
            "type": ntype,
            "input_type": INPUT_TYPE.get(ntype, "text"),
            "name": name,
            "label": p.get("label") or name,
            "placeholder": p.get("placeholder") or "",
            "help_text": p.get("help_text") or "",
            "default": p.get("default_value") or "",
            "options": [o for o in (p.get("options") or []) if isinstance(o, dict)],
            "width": p.get("width") or "full",
            "required": bool(p.get("required")),
            "rules": rules,
            "mautic_field": p.get("mautic_field") or name,
            "consent": bool(ntype == "form.consent_field"),
            "consent_text": p.get("consent_text") or "",
            "policy_url": p.get("policy_url") or "",
            "multiple": bool(p.get("multiple")),
            "inline": bool(p.get("inline")),
            "site_key": p.get("site_key") or "",
            "provider": p.get("provider") or "",
        }

    # -------------------------------------------------- HTML
    def _form_inner(self, schema: dict, fields: list[dict], form_id: str,
                    ajax: bool | None) -> str:
        root = schema.get("root") or {}
        p = root.get("props") or {}
        layout = p.get("layout", "stacked")
        action = p.get("action") or ""
        method = p.get("method", "POST")
        use_ajax = p.get("submit_ajax", True) if ajax is None else ajax
        color = p.get("theme_color") or _t(self.t, "brand")

        open_tag = (
            f'<form id="{esc(form_id)}" class="ce-form ce-layout-{esc(layout)}" '
            f'method="{esc(method.lower())}" '
            + (f'action="{esc(action)}"' if action else "")
            + f'{" novalidate" if use_ajax else ""} '
            f'data-ajax="{"1" if use_ajax else "0"}" '
            f'data-mautic-form-id="{esc(p.get("mautic_form_id") or "")}" '
            f'data-success="{esc(p.get("success_message") or "")}" '
            f'data-error="{esc(p.get("error_message") or "")}" novalidate>'
        )
        body: list[str] = [open_tag]

        # 分组（section）
        groups = self._group_by_section(root)
        for title, desc, items in groups:
            if title:
                body.append(f'<fieldset class="ce-fieldset"><legend>{esc(title)}</legend>')
                if desc:
                    body.append(f'<p class="ce-desc">{esc(desc)}</p>')
            inner = [self._field_html(f) for f in items]
            body.append(self._wrap_grid(inner, layout))
            if title:
                body.append("</fieldset>")

        body.append(self._submit_html(p, color))
        body.append(
            '<div class="ce-status" role="status" aria-live="polite" hidden></div>'
            # 隐藏域：UTM 透传
            + "".join(
                f'<input type="hidden" name="{esc(k)}" data-ce-utm="{esc(k)}">'
                for k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
            )
            + '<input type="text" name="ce_website" tabindex="-1" autocomplete="off" '
              'style="position:absolute;left:-9999px;opacity:0" aria-hidden="true">'
        )
        body.append("</form>")
        return "\n".join(x for x in body if x)

    def _group_by_section(self, root: dict) -> list[tuple[str, str, list[dict]]]:
        """按 form.section 分组；无 section 时全部字段归为一组。

        遍历时直接把字段 append 到所属 group（``out[-1][2]``），
        heading 也开启一个新 group，这样"标题 + 下面字段"能对应上。
        """
        out: list[tuple[str, str, list[dict]]] = []

        def walk(node: dict) -> None:
            for ch in node.get("children") or []:
                ntype = ch.get("type", "")
                if ntype == "form.section":
                    sp = ch.get("props") or {}
                    out.append((sp.get("title") or "", sp.get("description") or "", []))
                    self._section_fields(ch, out)
                elif ntype == "form.heading":
                    out.append(((ch.get("props") or {}).get("text") or "", "", []))
                elif ntype in INPUT_TYPE or ntype == "form.captcha":
                    m = self._field_model(ch)
                    if out:
                        out[-1][2].append(m)
                    else:
                        out.append(("", "", [m]))
                elif ch.get("container"):
                    walk(ch)

        walk(root)
        # 丢弃没有字段的空 group（只有标题），避免渲染空 fieldset
        return [g for g in out if g[2]] or [("", "", [])]

    def _section_fields(self, section: dict, out: list | None = None) -> list[dict]:
        items: list[dict] = []
        for ch in section.get("children") or []:
            ntype = ch.get("type", "")
            if ntype in INPUT_TYPE or ntype == "form.captcha":
                m = self._field_model(ch)
                items.append(m)
                if out:
                    out[-1][2].append(m)
            elif ch.get("container"):
                sub = self._section_fields(ch, out)
                items.extend(sub)
        return items

    def _wrap_grid(self, html_parts: list[str], layout: str) -> str:
        if not html_parts:
            return ""
        if layout == "two_col":
            half = [h for h in html_parts if 'data-width="half"' in h]
            full = [h for h in html_parts if 'data-width="half"' not in h]
            rows = []
            for i in range(0, len(half), 2):
                rows.append('<div class="ce-row">' + "".join(half[i:i + 2]) + "</div>")
            return '<div class="ce-grid">' + "".join(rows) + "".join(full) + "</div>"
        return '<div class="ce-grid">' + "".join(html_parts) + "</div>"

    def _field_html(self, f: dict) -> str:
        name = esc(f["name"])
        fid = f"ce-{slugify(f['name'], f['node_id'])}"
        width_class = "ce-col ce-col-half" if f["width"] == "half" else "ce-col"
        req = " required" if f["required"] else ""
        aria = ' aria-required="true"' if f["required"] else ""
        described = f' aria-describedby="{esc(fid)}-help"' if f["help_text"] else ""
        cls = "ce-field ce-field-invalid" if f["type"] == "form.captcha" else "ce-field"

        # hidden
        if f["input_type"] == "hidden":
            return (f'<input type="hidden" name="{name}" '
                    f'value="{esc(f["default"])}" data-width="{esc(f["width"])}">')

        # honeypot
        if f["type"] == "form.captcha" and f["provider"] == "honeypot":
            return ('<div class="ce-hp" aria-hidden="true">'
                    '<label>请勿填写<input type="text" name="ce_hp" tabindex="-1"></label></div>')

        if f["input_type"] == "textarea":
            control = (f'<textarea id="{esc(fid)}" name="{name}" rows="{(f.get("rows") or 4)}" '
                       f'placeholder="{esc(f["placeholder"])}"{req}{aria}{described} '
                       f'class="ce-input">{esc(f["default"])}</textarea>')
        elif f["input_type"] == "select":
            opts = "".join(
                f'<option value="{esc(o.get("value"))}"'
                f'{" selected" if o.get("value") == f["default"] else ""}>'
                f'{esc(o.get("label"))}</option>' for o in f["options"]
            )
            control = (f'<select id="{esc(fid)}" name="{name}"{req}{aria}{described} '
                       f'class="ce-input">'
                       f'<option value="">{esc(f["placeholder"] or "请选择")}</option>{opts}</select>')
        elif f["input_type"] in ("radio", "checkbox"):
            name_attr = name + ("[]" if f["input_type"] == "checkbox" and
                                len(f["options"]) > 1 else "")
            opts = "".join(
                f'<label class="ce-choice">'
                f'<input type="{f["input_type"]}" name="{esc(name_attr)}" '
                f'value="{esc(o.get("value"))}">'
                f'<span>{esc(o.get("label"))}</span></label>' for o in f["options"]
            )
            control = (f'<div class="ce-choices{" is-inline" if f["inline"] else ""}" '
                       f'id="{esc(fid)}" role="{f["input_type"]}group"{aria}>'
                       f'{opts}</div>'
                       + (f'<input type="hidden" name="{name}" value="" '
                          f'data-ce-multi="{esc(name)}">' if f["multiple"] else ""))
        elif f["type"] == "form.consent_field":
            label_html = esc(f["label"])
            if f["policy_url"]:
                label_html += (f' <a href="{esc(f["policy_url"])}" target="_blank" '
                               f'rel="noopener">查看政策</a>')
            control = (f'<label class="ce-consent">'
                       f'<input type="checkbox" id="{esc(fid)}" name="{name}" '
                       f'value="1"{req}>'
                       f'<span>{label_html}</span></label>'
                       + (f'<p class="ce-help">{esc(f["consent_text"])}</p>'
                          if f["consent_text"] else ""))
        else:
            extra = ""
            r = f["rules"]
            if r.get("minLength"):
                extra += f' minlength="{r["minLength"]}"'
            if r.get("maxLength"):
                extra += f' maxlength="{r["maxLength"]}"'
            if r.get("pattern"):
                extra += f' pattern="{esc(r["pattern"])}"'
            if r.get("min") is not None and r.get("type") == "number":
                extra += f' min="{r["min"]}"'
            if r.get("max") is not None and r.get("type") == "number":
                extra += f' max="{r["max"]}"'
            if r.get("min") and r.get("type") != "number":
                extra += f' min="{esc(str(r["min"]))}"'
            if r.get("max") and r.get("type") != "number":
                extra += f' max="{esc(str(r["max"]))}"'
            control = (f'<input id="{esc(fid)}" type="{esc(f["input_type"])}" name="{name}" '
                       f'value="{esc(f["default"])}" placeholder="{esc(f["placeholder"])}"'
                       f'{extra}{req}{aria}{described} class="ce-input" '
                       f'autocomplete="{esc(_autocomplete(f))}">')

        help_html = (f'<p class="ce-help" id="{esc(fid)}-help">{esc(f["help_text"])}</p>'
                     if f["help_text"] else "")
        label_html = ""
        if f["input_type"] not in ("radio", "checkbox") and f["type"] != "form.consent_field":
            star = '<span class="ce-req" aria-hidden="true">*</span>' if f["required"] else ""
            label_html = f'<label class="ce-label" for="{esc(fid)}">{esc(f["label"])}{star}</label>'

        return (f'<div class="{cls} {width_class}" data-width="{esc(f["width"])}" '
                f'data-field="{name}">{label_html}{control}'
                f'<p class="ce-error" role="alert" hidden></p>{help_html}</div>')

    def _submit_html(self, p: dict, color: str) -> str:
        label = p.get("submit_label") or "提交"
        variant = "ce-btn-primary"
        hint = ('<p class="ce-privacy-hint">提交即表示你同意我们的'
                '<a href="/privacy" target="_blank" rel="noopener">隐私政策</a></p>'
                if p.get("show_privacy_hint", True) else "")
        return (f'<div class="ce-actions"><button type="submit" class="ce-submit {variant}" '
                f'style="background:{esc(color)}">{esc(label)}</button>{hint}</div>')

    # -------------------------------------------------- 独立页
    def _standalone(self, schema: dict, fields: list[dict], form_id: str,
                    with_js: bool, ajax: bool | None) -> str:
        doc = schema.get("doc") or {}
        tokens = self.t
        body = self._form_inner(schema, fields, form_id, ajax)
        css = self._css(tokens)
        js = self._js() if with_js else ""
        rules_json = json.dumps(
            {f["name"]: {"rules": f["rules"], "label": f["label"]} for f in fields},
            ensure_ascii=False,
        )
        return f"""<!DOCTYPE html>
<html lang="{esc(doc.get('locale', 'zh-CN'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(doc.get('name') or '表单')}</title>
<style>{css}</style>
</head>
<body>
<main class="ce-form-wrap">{body}</main>
<script id="ce-form-rules" type="application/json">{rules_json}</script>
{js}
</body>
</html>"""

    def _css(self, tokens: dict) -> str:
        return f""".ce-form{{max-width:560px;margin:0 auto;font-family:{_t(tokens,'font_family')};
color:{_t(tokens,'text')}}}
.ce-form-wrap{{max-width:560px;margin:0 auto;padding:32px 16px;background:{_t(tokens,'bg_subtle')}}}
.ce-fieldset{{border:0;padding:0;margin:0 0 24px}}
.ce-fieldset legend{{font-size:18px;font-weight:700;color:{_t(tokens,'secondary')};
padding:0 0 12px}}
.ce-desc{{color:{_t(tokens,'text_muted')};font-size:14px;margin:-8px 0 16px}}
.ce-grid{{display:flex;flex-wrap:wrap;gap:16px}}
.ce-col{{flex:1 1 100%;min-width:0}}
.ce-col-half{{flex:1 1 calc(50% - 8px)}}
.ce-field{{display:flex;flex-direction:column;gap:6px}}
.ce-label{{font-size:14px;font-weight:600}}
.ce-req{{color:{_t(tokens,'danger')}}}
.ce-input{{width:100%;padding:10px 12px;font-size:15px;font-family:inherit;
border:1px solid {tokens.get('border','#e5e7eb')};border-radius:{_t(tokens,'radius')};
background:#fff;color:inherit;box-sizing:border-box}}
.ce-input:focus{{outline:2px solid {_t(tokens,'brand')};outline-offset:1px}}
.ce-field-invalid .ce-input{{border-color:{_t(tokens,'danger')}}}
.ce-help{{font-size:12px;color:{_t(tokens,'text_muted')};margin:0}}
.ce-error{{font-size:12px;color:{_t(tokens,'danger')};margin:0}}
.ce-choices{{display:flex;flex-direction:column;gap:8px}}
.ce-choices.is-inline{{flex-direction:row;flex-wrap:wrap;gap:16px}}
.ce-choice{{display:flex;align-items:center;gap:6px;font-size:14px}}
.ce-consent{{display:flex;gap:8px;align-items:flex-start;font-size:13px}}
.ce-submit{{border:0;color:#fff;font-size:16px;font-weight:600;padding:12px 28px;
border-radius:{_t(tokens,'radius')};cursor:pointer;width:100%}}
.ce-submit:disabled{{opacity:.6;cursor:progress}}
.ce-privacy-hint{{font-size:12px;color:{_t(tokens,'text_muted')};text-align:center}}
.ce-status{{margin-top:16px;padding:12px;border-radius:{_t(tokens,'radius')};font-size:14px}}
.ce-status[data-state="ok"]{{background:{_t(tokens,'brand_light')};color:{_t(tokens,'brand_dark')}}}
.ce-status[data-state="error"]{{background:#fde8e8;color:{_t(tokens,'danger')}}}
.ce-hp{{position:absolute;left:-9999px}}
@media (max-width:560px){{.ce-col-half{{flex:1 1 100%}}}}"""

    def _js(self) -> str:
        return r"""(function(){
  'use strict';
  var RULES = {};
  try { RULES = JSON.parse(document.getElementById('ce-form-rules').textContent||'{}'); } catch(e){}
  function $(s,r){return (r||document).querySelector(s)}
  function $$(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))}

  // UTM 透传
  var qs = new URLSearchParams(location.search);
  $$('[data-ce-utm]').forEach(function(el){
    var v = qs.get(el.getAttribute('data-ce-utm'));
    if (v) el.value = v;
  });

  function msg(name, text){
    var f = $('[data-field="'+name+'"]');
    if(!f) return;
    var e = $('.ce-error', f);
    if(e){ e.textContent = text||''; e.hidden = !text; }
    f.classList.toggle('ce-field-invalid', !!text);
  }

  function validateField(f){
    var name = f.name, cfg = RULES[name]||{}, rules = cfg.rules||{};
    if (f.type === 'hidden') return true;
    var val = (f.type === 'checkbox') ? f.checked : (f.value||'').trim();
    if (name === 'ce_website' && val) return false;
    if (rules.required && !val) { msg(name, (cfg.label||'该字段')+'为必填'); return false; }
    if (val) {
      if (rules.type === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(val)) {
        msg(name, '邮箱格式不正确'); return false;
      }
      if (rules.type === 'number') {
        var n = Number(val);
        if (rules.min !== undefined && n < rules.min) { msg(name, '不能小于 '+rules.min); return false; }
        if (rules.max !== undefined && n > rules.max) { msg(name, '不能大于 '+rules.max); return false; }
      }
      if (rules.minLength && val.length < rules.minLength) { msg(name, '至少 '+rules.minLength+' 个字符'); return false; }
      if (rules.maxLength && val.length > rules.maxLength) { msg(name, '最多 '+rules.maxLength+' 个字符'); return false; }
      if (rules.pattern) {
        try { if (!new RegExp(rules.pattern).test(val)) { msg(name, '格式不正确'); return false; } }
        catch(e){}
      }
    }
    msg(name, '');
    return true;
  }

  function validateForm(form){
    var ok = true, first = null;
    $$('[data-field]', form).forEach(function(f){
      var field = f.closest('.ce-field');
      if (!field) return;
      var okOne = validateField(f);
      if (!okOne && !first) first = field;
      ok = ok && okOne;
    });
    if (first) { first.scrollIntoView({behavior:'smooth', block:'center'}); }
    return ok;
  }

  function status(form, state, text){
    var box = $('.ce-status', form);
    if (!box) return;
    box.hidden = !text;
    box.textContent = text||'';
    if (text) box.setAttribute('data-state', state); else box.removeAttribute('data-state');
  }

  function serialize(form){
    var data = {};
    new FormData(form).forEach(function(v,k){ data[k]=v; });
    // 多选 checkbox：合并为数组
    $$('[data-ce-multi]', form).forEach(function(h){
      var key = h.getAttribute('data-ce-multi');
      var vals = $$('input[name="'+key+'[]"]:checked', form).map(function(i){return i.value});
      data[key] = vals;
    });
    return data;
  }

  function ready(fn){
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function(){
    var form = $('.ce-form');
    if (!form) return;
    form.addEventListener('input', function(e){
      var f = e.target;
      if (f && f.name) validateField(f);
    });
    form.addEventListener('submit', function(e){
      if (!validateForm(form)) { e.preventDefault(); status(form,'error', form.getAttribute('data-error')||'请检查表单'); return; }
      if (form.getAttribute('data-ajax') !== '1') return;  // 传统提交
      e.preventDefault();
      var btn = $('.ce-submit', form);
      var action = form.getAttribute('action') || window.location.href;
      if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = '提交中…'; }
      fetch(action, {
        method: (form.getAttribute('method')||'post').toUpperCase(),
        headers: {'Content-Type':'application/json','Accept':'application/json'},
        body: JSON.stringify(serialize(form))
      }).then(function(r){
        if (!r.ok) throw new Error('HTTP '+r.status);
        return r.status===204 ? {} : r.json().catch(function(){return {}});
      }).then(function(){
        form.reset();
        status(form,'ok', form.getAttribute('data-success')||'提交成功');
        if (window.dataLayer) { window.dataLayer.push({event:'ce_form_submit', form: form.id}); }
      }).catch(function(err){
        status(form,'error', (form.getAttribute('data-error')||'提交失败，请稍后重试')+'（'+err.message+'）');
      }).finally(function(){
        if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || '提交'; }
      });
    });
  });
})();"""


def _autocomplete(f: dict) -> str:
    name = f["name"].lower()
    if f["input_type"] == "email":
        return "email"
    if f["input_type"] == "tel":
        return "tel"
    m = {"firstname": "given-name", "lastname": "family-name", "fullname": "name",
         "name": "name", "company": "organization", "country": "country-name",
         "city": "address-level2", "postcode": "postal-code", "address": "street-address"}
    for k, v in m.items():
        if k in name:
            return v
    return "on"


def render_form(schema: dict, tokens: dict | None = None, **kw) -> str:
    return FormRenderer(tokens).render(schema, **kw)