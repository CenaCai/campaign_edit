"""内置组件：表单专用块。

表单的产物同时服务两端：
1. 导出为独立 HTML + JS（可直接落地到站点，POST 到任意 endpoint）；
2. 一键投递到 Mautic ``/api/forms``（字段映射见export/mautic.py）。
因此每个字段块都带 ``mautic_field`` 与 ``validation`` 元数据。
"""
from __future__ import annotations

from .registry import BlockRegistry

FIELD_COMMON = {
    "label": {"type": "string", "label": "标签", "default": "", "required": True},
    "name": {"type": "string", "label": "字段名", "default": "", "required": True},
    "required": {"type": "boolean", "label": "必填", "default": False},
    "placeholder": {"type": "string", "label": "占位符", "default": ""},
    "help_text": {"type": "string", "label": "辅助说明", "default": ""},
    "default_value": {"type": "string", "label": "默认值", "default": ""},
    "width": {"type": "string", "label": "宽度",
              "enum": ["full", "half"], "default": "full"},
    "mautic_field": {"type": "string", "label": "Mautic 字段名（留空自动映射）", "default": ""},
}


def _field(key: str, name: str, category: str, extra: dict, renderer: str) -> dict:
    props = dict(FIELD_COMMON)
    props.update(extra)
    return {
        "key": key, "name": name, "kind": ["form"], "category": category,
        "container": False, "renderer": renderer, "props_schema": props,
    }


def register(registry: BlockRegistry) -> None:
    specs: list[dict] = [
        {
            "key": "form.root", "root_kind": "form", "name": "表单根容器",
            "kind": ["form"], "category": "layout_only", "container": True,
            "renderer": "form_root",
            "props_schema": {
                "form_name": {"type": "string", "label": "表单名", "default": "",
                              "required": True},
                "submit_label": {"type": "string", "label": "提交按钮文案", "default": "提交"},
                "success_message": {"type": "string", "label": "成功提示",
                                     "default": "提交成功，我们会尽快与你联系。"},
                "error_message": {"type": "string", "label": "失败提示", "default": "提交失败，请稍后重试。"},
                "action": {"type": "string", "label": "提交地址(endpoint)", "default": ""},
                "method": {"type": "string", "label": "方法",
                           "enum": ["POST", "GET"], "default": "POST"},
                "mautic_form_id": {"type": "string", "label": "Mautic Form ID", "default": ""},
                "submit_ajax": {"type": "boolean", "label": "AJAX 提交（不跳页）", "default": True},
                "theme_color": {"type": "string", "label": "主题色", "default": "#c8102e"},
                "layout": {"type": "string", "label": "布局",
                           "enum": ["stacked", "inline", "two_col"], "default": "stacked"},
            },
            "style_defaults": {"background_color": "#ffffff"},
        },
        {
            "key": "form.section", "name": "表单分组标题", "kind": ["form"], "container": True,
            "category": "layout", "renderer": "form_section",
            "children_allowed": ["form.text_field", "form.email_field", "form.phone_field",
                                 "form.select_field", "form.radio_field", "form.checkbox_field",
                                 "form.textarea_field", "form.date_field", "form.hidden_field",
                                 "form.consent_field", "form.number_field"],
            "children_limit": {"max": 60},
            "props_schema": {
                "title": {"type": "string", "label": "分组标题", "default": ""},
                "description": {"type": "string", "label": "分组说明", "default": ""},
                "collapsible": {"type": "boolean", "label": "可折叠", "default": False},
            },
        },
        {
            "key": "form.heading", "name": "标题文本", "kind": ["form"], "container": False,
            "category": "text", "renderer": "form_heading",
            "props_schema": {
                "text": {"type": "string", "label": "文本", "default": "", "required": True},
                "level": {"type": "string", "enum": ["h1", "h2", "h3", "p"], "default": "h2"},
                "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
            },
        },
        _field("form.text_field", "单行文本", "form",
               {"placeholder": {"type": "string", "default": "请输入"},
                "min_length": {"type": "number", "label": "最小长度", "default": 0},
                "max_length": {"type": "number", "label": "最大长度", "default": 255},
                "pattern": {"type": "string", "label": "正则约束", "default": ""}},
               "form_field_text"),
        _field("form.email_field", "邮箱", "form",
               {"placeholder": {"type": "string", "default": "name@example.com"}},
               "form_field_email"),
        _field("form.phone_field", "手机号", "form",
               {"placeholder": {"type": "string", "default": "+44 7700 900000"},
                "country_code": {"type": "string", "label": "国家码(UK/US/CN)", "default": "UK"},
                "validate_pattern": {"type": "boolean", "label": "校验格式", "default": True}},
               "form_field_phone"),
        _field("form.number_field", "数字", "form",
               {"min": {"type": "number", "label": "最小值", "default": 0},
                "max": {"type": "number", "label": "最大值", "default": 0},
                "step": {"type": "number", "label": "步长", "default": 1}},
               "form_field_number"),
        _field("form.select_field", "下拉选择", "form",
               {"options": {"type": "array", "label": "选项", "default": [
                   {"label": "选项一", "value": "opt1"}]},
                "multiple": {"type": "boolean", "label": "多选", "default": False}},
               "form_field_select"),
        _field("form.radio_field", "单选", "form",
               {"options": {"type": "array", "label": "选项", "default": [
                   {"label": "选项一", "value": "opt1"}]},
                "inline": {"type": "boolean", "label": "横向排列", "default": False}},
               "form_field_radio"),
        _field("form.checkbox_field", "多选/同意条款", "form",
               {"options": {"type": "array", "label": "选项", "default": [
                   {"label": "选项一", "value": "opt1"}]},
                "inline": {"type": "boolean", "label": "横向排列", "default": False}},
               "form_field_checkbox"),
        _field("form.textarea_field", "多行文本", "form",
               {"rows": {"type": "number", "label": "行数", "default": 4},
                "max_length": {"type": "number", "label": "最大长度", "default": 2000}},
               "form_field_textarea"),
        _field("form.date_field", "日期", "form",
               {"min_date": {"type": "string", "label": "最早", "default": ""},
                "max_date": {"type": "string", "label": "最晚", "default": ""}},
               "form_field_date"),
        _field("form.hidden_field", "隐藏字段(UTM等)", "form", {}, "form_field_hidden"),
        {
            "key": "form.consent_field", "name": "同意条款（GDPR 必备）", "kind": ["form"],
            "container": False, "category": "form", "renderer": "form_field_consent",
            "props_schema": {
                "label": {"type": "string", "label": "条款文案", "default":
                          "我已阅读并同意隐私政策", "required": True},
                "policy_url": {"type": "string", "label": "隐私政策链接", "default": "",
                               "required": True},
                "required": {"type": "boolean", "label": "必须勾选", "default": True},
                "consent_text": {"type": "string", "label": "营销同意文案", "default": ""},
                "marketing_consent": {"type": "boolean", "label": "包含营销同意", "default": False},
            },
        },
        {
            "key": "form.submit", "name": "提交按钮", "kind": ["form"], "container": False,
            "category": "action", "renderer": "form_submit",
            "props_schema": {
                "label": {"type": "string", "label": "文案", "default": "提交", "required": True},
                "variant": {"type": "string", "enum": ["primary", "secondary", "ghost"],
                            "default": "primary"},
                "block": {"type": "boolean", "label": "通栏", "default": True},
                "show_privacy_hint": {"type": "boolean", "label": "显示隐私提示", "default": True},
            },
        },
        {
            "key": "form.captcha", "name": "人机验证占位（honeypot/recaptcha）",
            "kind": ["form"], "container": False, "category": "form",
            "renderer": "form_captcha",
            "props_schema": {
                "provider": {"type": "string", "enum": ["honeypot", "recaptcha_v3", "turnstile"],
                             "default": "honeypot"},
                "site_key": {"type": "string", "label": "site key", "default": ""},
            },
        },
    ]
    registry.register_many(specs)
    registry.register({
        "key": "form.root", "root_kind": "form", "name": "表单根容器",
        "kind": ["form"], "category": "layout_only", "container": True,
        "renderer": "form_root", "props_schema": specs[0]["props_schema"],
        "style_defaults": specs[0]["style_defaults"],
    }, root=True, replace=True)