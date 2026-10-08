"""组件注册表：定义「有哪些内容块、每个块能配什么属性、渲染成什么」。

这是模板、编辑器属性面板、渲染器、导出器共用的唯一来源。
第三方组件包（plugin）通过 ``register()`` 在运行时注入，无需改本文件。
"""
from __future__ import annotations

import threading
from typing import Any

from .schema import make_node  # noqa: F401  (便于 block 模块内构造示例)


class BlockSpec(dict):
    """组件定义。就是个 dict，加了 key 与静态构造糖。"""

    @property
    def key(self) -> str:
        return self["key"]

    @property
    def name(self) -> str:
        return self["name"]

    @property
    def container(self) -> bool:
        return bool(self.get("container"))

    def make(self, props: dict | None = None, node_id: str | None = None) -> dict[str, Any]:
        return make_node(self["key"], props, spec=dict(self), node_id=node_id)


class BlockRegistry:
    """线程安全的组件注册表。"""

    def __init__(self) -> None:
        self._specs: dict[str, BlockSpec] = {}
        self._roots: dict[str, BlockSpec] = {}
        self._lock = threading.RLock()

    # --- 注册 ---
    def register(self, spec: dict, *, root: bool = False, replace: bool = False) -> BlockSpec:
        key = spec.get("key")
        if not key:
            raise ValueError("组件定义缺少 key")
        bs = BlockSpec(spec)
        bs.setdefault("name", key)
        bs.setdefault("kind", ["email", "form", "landing"])
        bs.setdefault("category", "basic")
        bs.setdefault("props_schema", {})
        bs.setdefault("style_defaults", {})
        bs.setdefault("container", False)
        bs.setdefault("renderer", key)
        bs.setdefault("source", "builtin")
        with self._lock:
            if key in self._specs and not replace:
                raise ValueError(f"组件已存在: {key}（如需覆盖请传 replace=True）")
            self._specs[key] = bs
            if root:
                self._roots[bs.get("root_kind") or key] = bs
        return bs

    def register_many(self, specs: list[dict], **kw) -> list[BlockSpec]:
        return [self.register(s, replace=kw.pop("replace", False), **kw) for s in specs]

    def unregister(self, key: str) -> None:
        with self._lock:
            self._specs.pop(key, None)
            self._roots.pop(key, None)

    # --- 查询 ---
    def get(self, key: str | None) -> BlockSpec | None:
        if not key:
            return None
        return self._specs.get(key)

    def root_spec(self, kind: str) -> BlockSpec:
        spec = self._roots.get(f"{kind}.root") or self._roots.get(f"{kind}_root")
        if spec is None:
            # 兜底：取该 kind 的第一个容器组件
            for s in self._specs.values():
                if s.get("root_kind") == kind:
                    return s
            raise KeyError(f"未注册 {kind} 的 root 组件")
        return spec

    def list(self, kind: str | None = None, *, category: str | None = None,
             include_roots: bool = False) -> list[BlockSpec]:
        out = []
        for s in self._specs.values():
            if not include_roots and s in self._roots.values():
                continue
            if kind and kind not in s.get("kind", []):
                continue
            if category and s.get("category") != category:
                continue
            out.append(s)
        return sorted(out, key=lambda x: (x.get("category", ""), x["key"]))

    def categories(self, kind: str) -> list[dict]:
        cats: dict[str, dict] = {}
        for s in self.list(kind):
            c = s.get("category", "basic")
            cats.setdefault(c, {"key": c, "label": CATEGORY_LABEL.get(c, c), "count": 0})
            cats[c]["count"] += 1
        return list(cats.values())

    def as_api(self, kind: str | None = None) -> list[dict]:
        return [_public_spec(s) for s in self.list(kind)]


CATEGORY_LABEL = {
    "layout": "布局",
    "hero": "首屏",
    "text": "文本",
    "media": "图片/视频",
    "action": "按钮/行动点",
    "form": "表单控件",
    "social": "社交/分享",
    "commerce": "票务/商品",
    "trust": "信任背书",
    "layout_only": "容器",
}


def _public_spec(s: BlockSpec) -> dict:
    d = {k: v for k, v in s.items() if not k.startswith("_")}
    d["is_container"] = bool(s.get("container"))
    return d


# ---------------------------------------------------------------- 全局实例

registry = BlockRegistry()


def get_registry() -> BlockRegistry:
    return registry


def load_builtins() -> None:
    """加载内置组件（幂等：重复调用只注册一次）。"""
    if registry.get("email.root"):
        return
    from . import builtin_email, builtin_form, builtin_landing  # noqa: F401
    builtin_email.register(registry)
    builtin_form.register(registry)
    builtin_landing.register(registry)