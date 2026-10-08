# 插件目录（`plugins/`）

Campaign Edit 的第三方扩展包目录。**一个插件包就是一个含 `plugin.json` 的目录**
（或其 zip）。安装后，插件声明的组件 / 主题 / 模板 / 意图词条会在运行时注册，
编辑器的组件面板、属性面板、导出产物会自动生效。

## 目录约定

```
plugins/
├── acme.demo/            # 示例插件（随仓库提供，可直接安装）
│   ├── 0.1.0/            # 版本目录
│   │   └── plugin.json
│   └── README.md
└── <your.plugin>/        # 你自己的插件
    ├── plugin.json       # 必需
    ├── README.md         # 可选：给人看的说明
    └── assets/           # 可选：静态资源
```

## 快速上手

### 1. 生成骨架

界面「插件中心」→「生成插件骨架」，或：

```http
GET /api/v1/plugins/scaffold?directory=D:/plugins/my.plugin&key=my.plugin&name=My Plugin
```

### 2. 安装

界面「插件中心」→「安装本地插件」，填目录绝对路径；
或：

```http
POST /api/v1/plugins/install
{ "path": "D:/plugins/my.plugin", "activate": true }
```

安装前会返回 `plan`（将要注册什么），确认后才写入运行时。

### 3. 验证

```bash
# 组件是否出现在编辑器左栏
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/blocks?kind=landing" | jq '.[] | select(.key|startswith("acme."))'

# 单组件预览
curl -X POST http://localhost:8000/api/v1/blocks/preview \
  -H "Content-Type: application/json" \
  -d '{"type":"acme.banner","props":{"text":"合作伙伴"}}'
```

## 安全边界（重要）

**插件包不允许执行任意代码。**

- `plugin.json` 只能声明**数据**，不能携带可执行逻辑
- `renderer` 必须取自宿主白名单（27 个函数，见 `backend/app/plugins/manifest.py`）
- 需要新的渲染逻辑时，在 `backend/app/render/generic.py` 注册并走代码评审
- 远程安装默认关闭（`PLUGIN_ALLOW_REMOTE_INSTALL=false`）

这样做的理由：一旦插件能执行代码，安装它就等于授予代码执行权限，
即使有人工审核也无法覆盖第三方包被投毒的供应链风险。

## 停用与卸载

- **停用**（推荐）：软下线，移除运行时注册，**保留目录**，可随时恢复
- **卸载**：默认也是软卸载；`purge=true` 才会删除目录

已使用某组件的内容不受停用影响——schema 快照自带 props 与 style，
渲染器是宿主函数。

## 详见

- [`docs/06-extension.md`](../docs/06-extension.md) —— manifest 规范、组件开发流程、MCP 接入
- [`acme.demo/README.md`](acme.demo/README.md) —— 示例插件说明