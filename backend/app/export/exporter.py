"""代码导出：把 Block Schema 变成可交付的产物。

导出目标
--------
``single_html``  单文件（邮件 / 落地页），可直接投放
``bundle``      zip 目录：HTML + tokens.css + schema.json + README + 可选多页
``scaffold``    Vite 工程脚手架（src/ 拆分 + dev server + build 脚本）
``mautic``      推送到 Mautic（emails / forms / pages）
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from ..config import settings
from ..models import ContentKind
from ..render import render, resolve_tokens
from ..render.theme import TOKEN_META, default_tokens, tokens_to_css
from .templates import validate_schema
from .tracking_and_schema import inject_tracking, inject_tracking_js


def _stamp(name: str) -> str:
    import re
    s = re.sub(r"[^\w\-]+", "-", (name or "content").strip().lower()).strip("-")
    return s[:60] or "content"


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def export_single_html(schema: dict, tokens: dict | None = None, *,
                       inline: bool = True, asset_mode: str = "auto",
                       db=None, bundle_dir: Path | None = None,
                       inject_tracking_opt: bool = True) -> dict[str, Any]:
    """单文件 HTML。inline=True 时把 tokens.css 与组件 CSS 全内联。

    asset_mode：auto | inline | bundle | cdn | keep
    - auto：邮件走 inline（客户端不认相对路径），其余保持原样
    - inline：本地资产转 data URI
    - bundle：需要 bundle_dir，资产落到该目录的 assets/ 下
    - cdn：替换为资产 URL（需已上传对象存储）
    """
    kind = schema.get("kind")
    toks = tokens or resolve_tokens(schema)
    assets_info: dict[str, Any] = {}
    effective = schema

    # 追踪注入：把 tracking 配置写进所有链接的 href（改 schema 而非改 HTML，
    # 这样预览 / 导出 / Mautic 投递三条链路自动一致）
    tracking_info: dict[str, Any] = {}
    if inject_tracking_opt:
        effective, tracking_info = inject_tracking(effective)

    if db is not None:
        from ..assets.service import asset_url_for, bundle_assets, inline_assets_in_schema
        mode = asset_mode or "auto"
        if mode == "auto":
            mode = "inline" if kind == "email" else "keep"
        if mode == "inline":
            effective, assets_info = inline_assets_in_schema(schema, db)
        elif mode == "bundle" and bundle_dir is not None:
            r = bundle_assets(db, schema, bundle_dir)
            effective = r["schema"]
            assets_info = {"copied": r["copied"], "failed": r["failed"],
                           "total": r["total"]}
        elif mode == "cdn":
            _replace_with_urls(effective, db, asset_url_for)
            assets_info = {"mode": "cdn"}

    html = render(effective, tokens=toks)
    if tracking_info.get("utm"):
        html = inject_tracking_js(html, tracking_info["utm"])
    return {
        "filename": f"{_stamp(schema.get('doc', {}).get('name'))}.html",
        "html": html,
        "css": tokens_to_css(toks) if not inline else "",
        "inline": inline,
        "kind": kind,
        "assets": assets_info,
        "tracking": tracking_info,
    }


def _replace_with_urls(schema: dict, db, resolver) -> None:
    """把 schema 里的 asset key 换成可访问URL（就地修改）。"""
    from ..assets.service import collect_asset_refs
    from ..assets.storage import is_asset_key

    refs = set(collect_asset_refs(schema))

    def walk(node: dict) -> None:
        props = node.get("props") or {}
        for k, v in list(props.items()):
            if isinstance(v, str) and v in refs:
                props[k] = resolver(v, db)
        for arr in props.values():
            if isinstance(arr, list):
                for item in arr:
                    if isinstance(item, dict):
                        for k, v in list(item.items()):
                            if isinstance(v, str) and v in refs:
                                item[k] = resolver(v, db)
        for ch in node.get("children") or []:
            if isinstance(ch, dict):
                walk(ch)

    walk(schema.get("root") or {})


def export_bundle(schema: dict, tokens: dict | None = None, *,
                  out_root: str | Path | None = None, db=None) -> dict[str, Any]:
    """zip bundle：HTML + tokens.css + schema.json + README + assets/。

    带 db 时自动把引用的本地资产复制进 assets/ 并重写 schema 里的引用为相对路径，
    产物因此是**自包含**的：解压后 index.html + assets/ 可直接部署。
    """
    kind = schema.get("kind")
    doc = schema.get("doc") or {}
    toks = tokens or resolve_tokens(schema)
    v = validate_schema(schema)
    if not v["ok"]:
        raise ValueError(f"schema 不合法，无法导出: {v.get('error')}")

    base = _stamp(doc.get("name"))
    root = Path(out_root or settings.export_dir) / f"{base}-{doc.get('key', 'v1')}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    assets_info: dict[str, Any] = {}
    effective = schema
    if db is not None:
        from ..assets.service import bundle_assets
        r = bundle_assets(db, schema, root)
        effective = r["schema"]
        assets_info = {"copied": r["copied"], "failed": r["failed"],
                       "total": r["total"]}

    _write(root / "index.html", render(effective, tokens=toks))
    _write(root / "tokens.css", tokens_to_css(toks))
    _write(root / "schema.json", json.dumps(effective, ensure_ascii=False, indent=2))
    if kind == ContentKind.FORM:
        _write(root / "fields.json", json.dumps(
            _form_fields_summary(effective), ensure_ascii=False, indent=2))
    _write(root / "README.md", _readme(effective, toks, assets_info))
    _write(root / "campaign-edit.json", json.dumps({
        "generator": f"{settings.app_name} {settings.app_version}",
        "kind": kind, "key": doc.get("key"), "name": doc.get("name"),
        "schema_version": schema.get("schema_version"),
        "assets": {"count": assets_info.get("total", 0),
                   "copied": len(assets_info.get("copied", []))},
    }, ensure_ascii=False, indent=2))

    zip_path = root.with_suffix(".zip")
    _zip_dir(root, zip_path)
    return {"dir": str(root), "zip": str(zip_path),
            "files": sorted(p.name for p in root.iterdir()),
            "assets": assets_info}


def export_scaffold(schema: dict, tokens: dict | None = None, *,
                    project_name: str | None = None,
                    out_root: str | Path | None = None) -> dict[str, Any]:
    """Vite 工程脚手架：适合交给前端继续开发。"""
    kind = schema.get("kind")
    doc = schema.get("doc") or {}
    toks = tokens or resolve_tokens(schema)
    name = _stamp(project_name or doc.get("name"))
    root = Path(out_root or settings.export_dir) / f"{name}-scaffold"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    entry_html = render(schema, tokens=toks)
    # 提取出 <style> 内容单独成文件，保持入口干净
    css_body = _extract_style(entry_html)
    head_extra = _extract_head_meta(entry_html)
    body = _extract_body(entry_html)

    _write(root / "index.html", f"""<!DOCTYPE html>
<html lang="{doc.get('locale', 'zh-CN')}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  {head_extra}
  <link rel="stylesheet" href="./src/styles/tokens.css" />
  <link rel="stylesheet" href="./src/styles/components.css" />
  <title>{doc.get('name', 'Campaign')}</title>
</head>
<body>
{body}
  <script type="module" src="./src/main.js"></script>
</body>
</html>
""")
    _write(root / "src" / "styles" / "tokens.css", tokens_to_css(toks))
    _write(root / "src" / "styles" / "components.css", css_body)
    _write(root / "src" / "main.js", _scaffold_js(kind))
    _write(root / "src" / "schema.json", json.dumps(schema, ensure_ascii=False, indent=2))
    _write(root / "package.json", json.dumps({
        "name": name, "private": True, "version": "0.1.0", "type": "module",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "devDependencies": {"vite": "^5.4.0"},
    }, ensure_ascii=False, indent=2))
    _write(root / "vite.config.js", """import { defineConfig } from 'vite'

export default defineConfig({
  base: './',
  build: { outDir: 'dist', assetsDir: 'assets' }
})
""")
    _write(root / ".gitignore", "node_modules\ndist\n.DS_Store\n")
    _write(root / "README.md", _scaffold_readme(schema, toks))
    _write(root / "campaign-edit.json", json.dumps({
        "generator": f"{settings.app_name} {settings.app_version}", "kind": kind,
        "source": doc.get("key"), "note": "由 Campaign Edit 导出的 Vite 脚手架",
    }, ensure_ascii=False, indent=2))

    zip_path = root.with_suffix(".zip")
    _zip_dir(root, zip_path)
    return {"dir": str(root), "zip": str(zip_path)}


# ---------------------------------------------------------------- 工具

def _zip_dir(root: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(root.parent))


def _extract_style(html: str) -> str:
    import re
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))


def _extract_head_meta(html: str) -> str:
    import re
    head = re.search(r"<head[^>]*>(.*?)</head>", html, re.S | re.I)
    if not head:
        return ""
    out = []
    for m in re.findall(r"<meta[^>]+>", head.group(1), re.I):
        if "<style" in m:
            continue
        out.append("  " + m)
    return "\n".join(out)


def _extract_body(html: str) -> str:
    import re
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    body = m.group(1) if m else html
    # 移除内联 <style>（已拆出）与 <script>（已进 main.js）
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.S | re.I)
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", body, re.S | re.I)
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S | re.I)
    extra = "\n".join(scripts)
    out = body.strip()
    if extra:
        out += f'\n  <script>\n{extra}\n  </script>'
    return out


def _form_fields_summary(schema: dict) -> list[dict]:
    from ..render.form import FormRenderer
    return FormRenderer().collect_fields(schema.get("root") or {})


def _scaffold_js(kind: str) -> str:
    base = """// 由 Campaign Edit 生成的入口文件。
// 这里只放"行为增强"；内容与样式均在 HTML/CSS 中，no-JS 也能完整阅读。
document.addEventListener('DOMContentLoaded', () => {
  // 示例：把来源 URL 的 query 参数回填到隐藏域
  const params = new URLSearchParams(location.search);
  document.querySelectorAll('[data-ce-utm]').forEach((el) => {
    const v = params.get(el.getAttribute('data-ce-utm'));
    if (v) el.value = v;
  });
  console.info('[Campaign Edit] scaffold ready');
});
"""
    if kind == ContentKind.FORM:
        base += """
// 表单提交示例（换成你自己的 endpoint）
document.querySelectorAll('.ce-form').forEach((form) => {
  form.addEventListener('submit', async (e) => {
    if (form.dataset.ajax !== '1') return;
    e.preventDefault();
    const btn = form.querySelector('.ce-submit');
    btn && (btn.disabled = true);
    try {
      const res = await fetch(form.action || location.href, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.fromEntries(new FormData(form).entries()))
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      form.reset();
      alert(form.dataset.success || '提交成功');
    } catch (err) {
      alert((form.dataset.error || '提交失败') + '：' + err.message);
    } finally {
      btn && (btn.disabled = false);
    }
  });
});
"""
    return base


def _readme(schema: dict, tokens: dict[str, Any],
            assets_info: dict[str, Any] | None = None) -> str:
    doc = schema.get("doc") or {}
    kind = schema.get("kind")
    kind_label = ContentKind.LABEL.get(kind, kind)
    assets_info = assets_info or {}
    n_assets = assets_info.get("total", 0)
    lines = [
        f"# {doc.get('name') or '未命名内容'}",
        "",
        f"- 类型：{kind_label}（`{kind}`）",
        f"- Key：`{doc.get('key') or '-'}`",
        f"- 语言：{doc.get('locale', 'zh-CN')}",
        f"- 主题：`{(schema.get('theme') or {}).get('theme_id') or 'default'}`",
        f"- 生成工具：{settings.app_name} {settings.app_version}",
        "",
        "## 文件说明",
        "",
        "| 文件 | 用途 |",
        "|---|---|",
        "| `index.html` | 可直接打开的单文件产物 |",
        "| `tokens.css` | 设计 token（颜色/间距/圆角），改这里即可换肤 |",
        "| `schema.json` | 结构化源文件，可重新导入 Campaign Edit继续编辑 |",
        "| `campaign-edit.json` | 生成元信息 |",
    ]
    if kind == ContentKind.FORM:
        lines += ["| `fields.json` | 字段清单（供 CRM / 数据层消费） |"]
    if n_assets:
        copied = len(assets_info.get("copied", []))
        lines += [f"| `assets/` | {copied}/{n_assets} 个图片资源（产物自包含） |"]
    lines += [
        "",
        "## 重新导入",
        "",
        "```bash",
        "curl -X POST http://localhost:8000/api/v1/contents \\",
        "  -H 'Content-Type: application/json' \\",
        f"  -d @schema.json",
        "```",
        "",
        "## 主题 token",
        "",
        "| token | 值 | 说明 |",
        "|---|---|---|",
    ]
    for k, v in tokens.items():
        meta = TOKEN_META.get(k, {})
        lines.append(f"| `--{k}` | `{v}` | {meta.get('label', '')} |")
    lines += [
        "",
        "## 注意",
        "",
        "- 邮件产物已做 Outlook/Gmail 兼容处理；修改结构后建议重新跑一次可投递性检查。",
        "- 落地页/表单产物请自行接入 Analytics 与真实 endpoint。",
    ]
    if n_assets:
        lines.append("- assets/ 已随包，部署时与 index.html 保持相对位置即可。")
    else:
        lines.append("- 本内容未引用本地资产；若图片是外链，请确认热链策略与版权。")
    lines
    return "\n".join(lines) + "\n"


def _scaffold_readme(schema: dict, tokens: dict[str, Any]) -> str:
    doc = schema.get("doc") or {}
    return f"""# {doc.get('name') or 'Campaign'}（Vite 脚手架）

由 {settings.app_name} {settings.app_version} 从 Block Schema 导出。

## 开发

```bash
npm install
npm run dev      # 本地预览
npm run build    # 产出 dist/
```

## 目录

```
index.html                 页面入口
src/styles/tokens.css      设计 token（换肤改这里）
src/styles/components.css  组件样式
src/main.js                行为增强（倒计时 / 表单提交 / 埋点）
src/schema.json            结构化源数据，可回灌 Campaign Edit
```

## 交接清单

- [ ] 替换占位图片为正式物料
- [ ] 接入真实表单 endpoint（`src/main.js`）
- [ ] 补 Analytics / 埋点事件
- [ ] 跑 Lighthouse 与多端真机验证
- [ ] 交回schema.json 以保持设计系统一致
"""


def export_tokens_css(tokens: dict | None = None) -> str:
    return tokens_to_css(tokens or default_tokens())