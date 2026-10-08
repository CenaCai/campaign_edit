# ACME Demo 插件

Campaign Edit 插件包。

## 目录结构

```
plugin.json          # manifest：声明式，不含可执行代码
README.md
```

## 注册了什么

- 组件 `acme.banner`（复用宿主渲染器 `generic_text`）
- 主题 `acme-brand`
- 模板 `acme_promo_landing`
- 意图词典扩展：`acme活动` / `acme新品` → landing

## 安装

后台「插件中心」→「安装本地插件」，选择本目录；或

```bash
curl -X POST http://localhost:8000/api/v1/plugins/install \
  -H 'Content-Type: application/json' \
  -d '{"path": "acme.demo"}'
```

## 约定

1. 组件 `key` 必须带命名空间，避免与内置块冲突。
2. `renderer` 只能取白名单中的值；要自定义渲染逻辑，
   请在宿主 `backend/app/render/generic.py` 注册（代码评审后合并）。
3. `props_schema` 驱动编辑器的属性面板，请补齐 `label` 与 `default`。
