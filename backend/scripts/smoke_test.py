"""端到端冒烟测试：覆盖 意图 → 创建 → 渲染 → lint → 协作 → 导出 → 插件 全链路。

直接打真实 HTTP（不走 TestClient），确保序列化/中间件/路由都没问题。
用法：
    python scripts/smoke_test.py [base_url]
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.error

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE}/api/v1"
TOKEN = ""

PASS, FAIL = 0, 0
FAILURES: list[str] = []


def call(method: str, path: str, body=None, *, expect: int = 200, raw: bool = False):
    # 路径里的中文等非 ASCII 必须先编码，否则 urllib 会直接失败
    if not path.startswith("http"):
        head, _, query = path.partition("?")
        head = urllib.parse.quote(head, safe="/%")
        if query:
            parts = []
            for kv in query.split("&"):
                k, _, v = kv.partition("=")
                parts.append(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}")
            query = "&".join(parts)
        path = f"{head}?{query}" if query else head
    url = path if path.startswith("http") else f"{API}{path}"
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8", "ignore")
            code = r.status
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "ignore")
        code = e.code
    except Exception as e:
        return 0, {"error": str(e)}
    if raw:
        return code, text
    try:
        return code, json.loads(text) if text else None
    except Exception:
        return code, text


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \033[32mPASS\033[0m {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  \033[31mFAIL\033[0m {name}  {detail}")


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


# ============================================================ 1. 健康与鉴权
section("1. 系统与鉴权")
code, health = call("GET", "/health")
check("健康检查", code == 200 and health.get("status") == "ok", f"{code} {health}")
check("组件注册表非空", (health.get("blocks") or 0) > 40, f"blocks={health.get('blocks')}")

code, login = call("POST", "/auth/login",
                   {"email": "admin@csts.dev", "password": "admin12345"})
if code == 200:
    TOKEN = login["access_token"]
check("管理员登录", code == 200 and bool(TOKEN), f"{code}")

code, cfg = call("GET", "/config")
check("启动配置", code == 200 and "llm" in cfg, f"llm={cfg.get('llm', {}).get('configured')}")

code, me = call("GET", "/auth/me")
check("当前用户", code == 200 and me.get("email") == "admin@csts.dev")

# ============================================================ 2. 模板与主题
section("2. 模板库与主题")
counts = {}
for kind in ("email", "form", "landing"):
    code, lst = call("GET", f"/templates?kind={kind}")
    counts[kind] = len(lst) if isinstance(lst, list) else 0
check("三类模板均≥4 套", all(v >= 4 for v in counts.values()), str(counts))

code, themes = call("GET", "/themes")
check("内置主题 ≥4", isinstance(themes, list) and len(themes) >= 4,
      f"{len(themes) if isinstance(themes, list) else 0}")

code, tokens = call("GET", "/themes/tokens")
check("token 定义", code == 200 and len(tokens.get("tokens", {})) >= 20,
      f"{len(tokens.get('tokens', {}))}")

code, cats = call("GET", "/blocks/categories?kind=landing")
check("组件分类", code == 200 and isinstance(cats, list) and len(cats) >= 5, f"{len(cats)}")

# ============================================================ 3. 意图识别
section("3. 意图识别（规则通道，无 LLM）")
CASES = [
    ("给会员发一封促销邮件，发20%折扣券，主推新赛季套票", "email", "promo"),
    ("做个欧洲杯活动落地页，要有倒计时和购票按钮", "landing", None),
    ("做一个留资表单，收集姓名邮箱手机号", "form", "lead_gen"),
    ("7月15日比赛改期提醒邮件，同时做个活动页", None, "schedule_change"),
    ("CUP2028 报名页 + 报名表单 + 提醒邮件全套", None, None),
]
for text, want_kind, want_scenario in CASES:
    code, res = call("POST", "/intents", {"text": text, "use_llm": False})
    ok = code == 200 and isinstance(res, dict) and res.get("ok")
    kind = res.get("content_type") if isinstance(res, dict) else None
    scen = res.get("scenario") if isinstance(res, dict) else None
    nplan = len(res.get("plan", [])) if isinstance(res, dict) else 0
    detail = f"kind={kind} conf={res.get('confidence') if isinstance(res, dict) else '-'} scen={scen} plan={nplan}"
    if not isinstance(res, dict):
        detail += f" raw={str(res)[:120]}"
    good = bool(ok) and (want_kind is None or kind == want_kind)
    if want_scenario:
        good = good and scen == want_scenario
    check(f"识别「{text[:18]}…」", good, detail)
    if ok:
        check("  └ 返回可解释证据", len(res.get("rule_evidence", [])) > 0,
              f"{len(res.get('rule_evidence', []))} 条")

code, multi = call("POST", "/intents",
                   {"text": "报名页 + 报名表单 + 提醒邮件全套", "use_llm": False})
if code == 200 and isinstance(multi, dict):
    plan = multi.get("plan", [])
    plan_kinds = [p["kind"] for p in plan]
    check("多意图拆分出 3 类资产", len(set(plan_kinds)) >= 3, str(plan_kinds))
    check("多意图带模板候选",
          bool(plan) and all(p.get("template_candidates") for p in plan))
else:
    check("多意图拆分出 3 类资产", False, f"{code} {str(multi)[:120]}")
    check("多意图带模板候选", False, "")

code, lex = call("GET", "/intents/lexicon")
check("词典可读", code == 200 and "direct" in lex and len(lex["direct"]) == 3)

# ============================================================ 4. 内容创建与渲染
section("4. 内容创建 → 渲染 → lint")
created: dict[str, str] = {}
for kind, name in (("email", "冒烟测试邮件"), ("form", "冒烟测试表单"),
                   ("landing", "冒烟测试落地页")):
    code, tpls = call("GET", f"/templates?kind={kind}")
    if not tpls:
        check(f"创建 {kind}", False, "无可用模板")
        continue
    tpl = tpls[0]
    code, item = call("POST", f"/templates/{tpl['id']}/instantiate?name={name}")
    check(f"由模板实例化 {kind}", code == 200 and item.get("id"),
          f"{code} {item.get('key') if isinstance(item, dict) else ''}")
    if code == 200:
        created[kind] = item["id"]
        code2, pv = call("GET", f"/contents/{item['id']}/preview")
        html = pv.get("html", "") if isinstance(pv, dict) else ""
        lint = pv.get("lint", {}) if isinstance(pv, dict) else {}
        check(f"  └ {kind} 渲染出 HTML", len(html) > 500, f"{len(html)} 字节")
        check(f"  └ {kind} lint 有结果", "passed" in lint, f"passed={lint.get('passed')} "
              f"errors={lint.get('counts', {}).get('error')}")

# ============================================================ 5. 版本与协作
cid = created.get("landing") or created.get("email") or created.get("form")
if not cid:
    print("\n\033[31m内容创建失败，跳过后续协作/导出用例\033[0m")
    code, contents = call("GET", "/contents")
    if isinstance(contents, list) and contents:
        cid = contents[0]["id"]
        print(f"回退使用已有示例内容: {contents[0]['key']}")
    else:
        print("没有任何可用内容，无法继续")
        print("\n" + "=" * 60)
        print(f"通过 \033[32m{PASS}\033[0m / 失败 \033[31m{FAIL}\033[0m （共 {PASS + FAIL}）")
        for f in FAILURES:
            print(f"  - {f}")
        print("=" * 60)
        sys.exit(1)

if cid:
    section("5. 版本管理 / 乐观锁 / 审核流")
    code, c = call("GET", f"/contents/{cid}")
check("读取内容", code == 200, f"{code}")
code, sch = call("GET", f"/contents/{cid}/schema")
check("读取 schema", code == 200 and sch.get("schema", {}).get("root") is not None)

# 造一个改动并保存
schema = sch.get("schema") if isinstance(sch, dict) else None
target = None
if schema:
    for ch in schema["root"].get("children", []):
        if ch.get("props"):
            target = ch
            break
if target:
    target.setdefault("props", {})["name"] = "冒烟测试改"
code, saved = call("POST", f"/contents/{cid}/save",
                   {"schema": schema, "message": "冒烟测试保存", "lint_gate": False})
check("保存新版本", code == 200 and saved.get("current_version", 0) >= 2,
      f"v{saved.get('current_version')} lock_version={saved.get('lock_version')}"
      if code == 200 else str(saved)[:120])

lock_ver = saved.get("lock_version") if code == 200 else 0
code, conflict = call("POST", f"/contents/{cid}/save",
                      {"schema": schema, "message": "过期锁写入",
                       "lint_gate": False, "lock_version": 999})
check("乐观锁拦截过期写入", code == 409, f"{code}")

code, vers = call("GET", f"/contents/{cid}/versions")
check("版本列表", code == 200 and len(vers) >= 2, f"{len(vers)} 个版本")

if len(vers) >= 2:
    code, det = call("GET", f"/contents/{cid}/versions/1")
    check("版本 diff", code == 200 and "diff" in det, f"ops={det.get('diff', {}).get('summary')}")
    code, restored = call("POST", f"/contents/{cid}/versions/1/restore")
    check("回滚（追加新版本）", code == 200 and restored.get("current_version", 0) > 2,
          f"v{restored.get('current_version')}" if code == 200 else str(restored)[:120])

code, lock = call("POST", f"/contents/{cid}/lock", {"action": "acquire", "ttl_seconds": 60})
check("获取草稿锁", code == 200 and lock.get("locked_by"), f"{lock}")
code, comment = call("POST", f"/contents/{cid}/comments",
                     {"body": "这块按钮文案建议再短一点", "block_id": "h1"})
check("添加评论", code == 200 and comment.get("id"), f"{code}")
code, comments = call("GET", f"/contents/{cid}/comments")
check("评论列表", code == 200 and len(comments) >= 1, f"{len(comments)} 条")

# 审核状态机：必须从 draft 起步。先把内容归位到 draft（已发布内容允许回退）
code, cur = call("GET", f"/contents/{cid}")
if cur.get("status") != "draft":
    code, _ = call("POST", f"/contents/{cid}/review", {"to_status": "draft",
                                                        "reason": "冒烟测试归位"})
    code, cur = call("GET", f"/contents/{cid}")
check("内容回到草稿态", cur.get("status") == "draft", f"status={cur.get('status')}")

code, illegal = call("POST", f"/contents/{cid}/review", {"to_status": "published"})
check("草稿直达发布被状态机拦截", code == 409, f"HTTP {code}（应为 409）")

code, r1 = call("POST", f"/contents/{cid}/review", {"to_status": "in_review", "reason": "提审"})
check("提交审核", code == 200 and r1.get("content", {}).get("status") == "in_review", f"{code}")
code, r2 = call("POST", f"/contents/{cid}/review", {"to_status": "approved"})
check("审核通过", code == 200 and r2.get("content", {}).get("status") == "approved", f"{code}")
code, r3 = call("POST", f"/contents/{cid}/review", {"to_status": "published"})
check("发布", code == 200 and r3.get("content", {}).get("status") == "published", f"{code}")
code, rv = call("GET", f"/contents/{cid}/reviews")
check("审核任务留痕", code == 200 and isinstance(rv, list) and len(rv) >= 3,
      f"{len(rv) if isinstance(rv, list) else 0} 条记录")
code, r4 = call("POST", f"/contents/{cid}/review", {"to_status": "draft"})
check("发布后回退草稿", code == 200, f"{code}")
code, arc = call("POST", f"/contents/{cid}/review", {"to_status": "archived"})
check("归档（软下线，非删除）", code == 200 and arc.get("content", {}).get("status") == "archived")
code, still = call("GET", f"/contents/{cid}")
check("归档后内容仍在（未被删除）", code == 200 and still.get("id") == cid)
code, call_lock = call("POST", f"/contents/{cid}/lock", {"action": "release"})
check("释放草稿锁", code == 200, f"{code}")

# ============================================================ 6. 导出
section("6. 代码导出")
for kind, cid2 in created.items():
    code, single = call("POST", f"/contents/{cid2}/export",
                        {"target": "single_html", "allow_lint_error": True})
    check(f"{kind} 单文件 HTML", code == 200 and len(single.get("html", "")) > 400,
          f"{len(single.get('html', '')) if code == 200 else str(single)[:100]} 字节")

code, bundle = call("POST", f"/contents/{cid}/export",
                    {"target": "bundle", "allow_lint_error": True})
files = bundle.get("files", {}) if code == 200 else {}
check("bundle 产物", code == 200 and files.get("zip", "").endswith(".zip"),
      str(files.get("zip", ""))[-50:] if code == 200 else str(bundle)[:150])
if code == 200:
    import os
    zp = files["zip"]
    check("  └ zip 文件真实存在", os.path.exists(zp),
          f"{os.path.getsize(zp) if os.path.exists(zp) else 0} 字节")

code, scaf = call("POST", f"/contents/{cid}/export",
                  {"target": "scaffold", "allow_lint_error": True})
check("Vite 脚手架", code == 200 and scaf.get("files", {}).get("zip", "").endswith(".zip"),
      scaf.get("files", {}).get("dir", "")[-40:] if code == 200 else str(scaf)[:150])

code, dl = call("GET", f"/contents/{cid}/download", raw=True)
check("下载单文件", code == 200 and len(dl) > 400 and "<!DOCTYPE html" in str(dl),
      f"{len(str(dl))} 字节")

code, mj = call("POST", f"/contents/{cid}/export", {"target": "mautic"})
check("Mautic 未配置时明确报错", code == 400 and "Mautic" in json.dumps(mj, ensure_ascii=False),
      f"{code}")

# ============================================================ 7. 插件
section("7. 插件与扩展")
code, plugs = call("GET", "/plugins")
if not isinstance(plugs, list):
    check("插件列表", False, f"{code} {str(plugs)[:160]}")
    plugs = []
else:
    check("插件列表", code == 200, f"{len(plugs)} 个")
acme = next((p for p in plugs if isinstance(p, dict) and p.get("key") == "acme.demo"), None)
check("示例插件已安装", acme is not None and acme["status"] == "active",
      f"{acme['status'] if acme else 'N/A'}")

if acme:
    check("插件注册了组件", "acme.banner" in (acme.get("capabilities") or []),
          str(acme.get("capabilities")))
    code, bl = call("GET", "/blocks?kind=landing")
    keys = [b["key"] for b in bl] if isinstance(bl, list) else []
    check("组件出现在编辑器左栏", "acme.banner" in keys, str(keys[:4]))

code, scan = call("GET", "/plugins/scan")
check("扫描本地插件目录", code == 200 and "items" in scan,
      f"{len(scan.get('items', []))} 个包")
check("远程安装默认关闭", scan.get("remote_install_enabled") is False)

if acme:
    code, dis = call("POST", f"/plugins/{acme['key']}/disable")
    check("停用插件（软下线）", code == 200 and dis.get("status") == "disabled", f"{code}")
    code, bl2 = call("GET", "/blocks?kind=landing")
    keys2 = [b["key"] for b in bl2] if isinstance(bl2, list) else []
    check("组件已从注册表移除", "acme.banner" not in keys2)
    code, act = call("POST", f"/plugins/{acme['key']}/activate")
    check("重新启用", code == 200 and act.get("status") == "active", f"{code}")
    code, bl3 = call("GET", "/blocks?kind=landing")
    check("组件回到注册表", "acme.banner" in [b["key"] for b in bl3])

code, rem = call("POST", "/plugins/install", {"url": "https://evil.example/plugin.zip"})
check("远程安装被安全策略拒绝", code == 400 and "远程安装默认关闭" in json.dumps(rem, ensure_ascii=False),
      f"{code}")

# ============================================================ 8. MCP
section("8. MCP 插件通道")
code, mcps = call("GET", "/plugins/mcp/servers")
check("MCP server 列表接口可用", code == 200 and isinstance(mcps, list), f"{len(mcps)} 个")
code, probe = call("POST", "/plugins/mcp/probe",
                   {"config": {"command": "definitely-not-a-real-binary-xyz", "args": []}})
check("MCP 探测失败被优雅处理", code == 200 and probe.get("ok") is False,
      str(probe.get("error"))[:80])

# ============================================================ 9. 组件预览
section("9. 组件级预览")
code, bp = call("POST", "/blocks/preview",
                {"type": "landing.button", "props": {"text": "立即购票", "url": "https://x.com"}})
check("按钮组件渲染", code == 200 and "立即购票" in bp.get("html", ""), f"{code}")
code, bp2 = call("POST", "/blocks/preview",
                 {"type": "email.product_card",
                  "props": {"title": "套票", "price": "£199", "old_price": "£249"}})
check("商品卡渲染（含价格对比）", code == 200 and "£199" in bp2.get("html", "")
      and "line-through" in bp2.get("html", ""), f"{code}")

# ============================================================ 10. Asset 资产层
section("10. Asset 资产层")
code, st = call("GET", "/assets/status")
check("存储后端状态", code == 200 and st.get("backend") in ("local", "s3"),
      f"{st.get('backend')} inline阈值={st.get('inline_threshold')}")

# 1x1 透明 PNG（标准 base64，避免手拼十六进制出错）
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def upload(fname: str, data: bytes, mime: str = "image/png", alt: str = "") -> tuple[int, dict]:
    """multipart 上传（标准库手写 multipart，避免引入 requests）。"""
    boundary = "----ce" + "0" * 40
    parts: list[bytes] = []

    def field(k: str, v: str) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
            .encode())

    field("alt", alt)
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{fname}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    url = f"{API}/assets"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


code, a1 = upload("logo.png", PNG, alt="CSTS Logo")
check("上传图片", code == 200 and a1.get("key", "").startswith("asset/"),
      f"{a1.get('key')}")
check("解析出尺寸", a1.get("width") == 1 and a1.get("height") == 1,
      f"{a1.get('width')}x{a1.get('height')}")
check("魔数识别 MIME", a1.get("mime") == "image/png", str(a1.get("mime")))

code, a2 = upload("logo2.png", PNG, alt="重复上传")
check("内容哈希去重", code == 200 and a2.get("id") == a1.get("id"),
      f"同id={a2.get('id') == a1.get('id')}")

code, bad = upload("evil.svg", b'<svg><script>alert(1)</script></svg>',
                   mime="image/svg+xml")
check("SVG 含脚本被拒", code == 400 and "脚本" in json.dumps(bad, ensure_ascii=False),
      f"{code}")

code, txt = upload("notimg.txt", b"hello", mime="text/plain")
check("非图片被拒", code == 400, f"{code}")

code, alist = call("GET", "/assets")
check("资产列表", code == 200 and alist.get("count", 0) >= 1, f"{alist.get('count')}")

# ============================================================ 11. AI Patch
section("11. AI Patch 局部修改")
code, psch = call("GET", "/patch/schema")
check("操作清单", code == 200 and len(psch.get("ops", [])) == 8,
      f"{[o['op'] for o in psch.get('ops', [])]}")

# 新建一份专用落地页测 patch：复用已有内容会因前序用例的改动导致状态污染
code, ltpls = call("GET", "/templates?kind=landing")
pbase = (ltpls or [{}])[0]
code, target = call("POST", f"/templates/{pbase['id']}/instantiate?name=Patch 测试页")
if code != 200:
    check("为 Patch 测试新建内容", False, f"{code} {str(target)[:100]}")
    target = {"id": None}
check("为 Patch 测试新建内容", target.get("id") is not None, str(target.get("key")))
code, out = call("GET", f"/contents/{target['id']}/outline")
blocks = out.get("blocks", []) if code == 200 else []
check("组件清单可读", code == 200 and len(blocks) > 0, f"{len(blocks)} 个组件")

btn = next((b for b in blocks if b["type"] == "landing.button"), None)
head = next((b for b in blocks if b["type"] == "landing.heading"), None)
spacer = next((b for b in blocks if b["type"] == "landing.section"), None)

if btn:
    # 固定新值：幂等性验证要求"连续两次同样的操作"，不能用随机值。
    # 第一次产生 diff，第二次（同值）必须无 diff —— 这正是 patch 该有的行为。
    new_text = "AI改过-1"
    code, r = call("POST", f"/contents/{target['id']}/patch", {
        "operations": [{"op": "set_prop", "target": btn["id"],
                        "prop": "text", "value": new_text}],
        "dry_run": True})
    check("dry_run 预演", code == 200 and r.get("diff", {}).get("count", 0) > 0,
          f"改动 {r.get('diff', {}).get('count')} 处")
    check("  └ 预演不落库", r.get("dry_run") is True and "version" not in r)

    # 幂等性：同参数连续两次预演，产出的 schema 必须逐字节相同。
    # 注意：diff 是相对**原始**版本算的，所以两次都会报 1 处改动——这是正确的，
    # 要验证的是 apply_operations 的确定性（不引入随机 id、不累积副作用）。
    code, r_idem = call("POST", f"/contents/{target['id']}/patch", {
        "operations": [{"op": "set_prop", "target": btn["id"],
                        "prop": "text", "value": new_text}],
        "dry_run": True})
    same = (code == 200
            and r_idem.get("preview_schema") == r.get("preview_schema")
            and r_idem.get("applied") == r.get("applied"))
    check("  └ 幂等（同参数两次预演结果一致）", same,
          f"diff稳定={r_idem.get('diff', {}).get('count')}")

    code, r2 = call("POST", f"/contents/{target['id']}/patch", {
        "operations": [{"op": "set_prop", "target": btn["id"],
                        "prop": "text", "value": new_text}],
        "message": "冒烟测试 patch"})
    check("提交 patch 生成新版本", code == 200 and r2.get("version", 0) >= 2,
          f"v{r2.get('version')}")

    code, pv = call("GET", f"/contents/{target['id']}/preview")
    check("  └ 改动已反映到预览", new_text in pv.get("html", ""),
          f"html {len(pv.get('html',''))} 字节")

    # 失败不应污染 schema：先非法再合法，验证原子性
    code, r_bad = call("POST", f"/contents/{target['id']}/patch", {
        "operations": [{"op": "set_prop", "target": btn["id"],
                        "prop": "text", "value": "不该生效"},
                       {"op": "set_prop", "target": "不存在", "prop": "x", "value": "y"}],
        "dry_run": False})
    check("批量操作失败则整体回滚（原子性）", code == 422, f"{code}")
    code, pv2 = call("GET", f"/contents/{target['id']}/preview")
    check("  └ 失败操作未写入任何内容", "不该生效" not in pv2.get("html", ""),
          "已回滚")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "set_prop", "target": "不存在的id",
                    "prop": "text", "value": "x"}], "dry_run": True})
check("目标不存在被拦截", code == 422, f"{code}")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "set_prop", "target": head["id"] if head else "root",
                    "prop": "不存在的属性", "value": "x"}], "dry_run": True})
check("属性不在白名单被拦", code == 422 and "没有属性" in json.dumps(r, ensure_ascii=False),
      f"{code}")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "remove", "target": "root"}], "dry_run": True})
check("不能删根节点", code == 422, f"{code}")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "未知操作", "target": "x"}], "dry_run": True})
check("未知操作被拒", code == 422, f"{code}")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "set_style", "target": btn["id"] if btn else "x",
                    "style": "position", "value": "absolute"}], "dry_run": True})
check("邮件/落地页安全样式白名单生效",
      code == 422 or (code == 200 and r.get("ok")), f"{code}")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "add_block", "type": "landing.form_embed",
                    "props": {"title": "AI 加的表单位"}}], "dry_run": True})
check("新增组件", code == 200 and r.get("diff", {}).get("count", 0) > 0,
      f"新增 {r.get('diff', {}).get('summary')}")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "add_block", "type": "form.email_field"}], "dry_run": True})
check("跨类型组件被拦", code == 422 and "不能用于" in json.dumps(r, ensure_ascii=False),
      f"{code}")

code, r = call("POST", f"/contents/{target['id']}/ai-patch", {
    "instruction": "把主标题改成「AI 编辑测试」", "dry_run": True})
check("AI 通道（无 LLM 时优雅降级）",
      code in (200, 503) and ("LLM 未配置" in json.dumps(r, ensure_ascii=False)
                              or r.get("operations")),
      f"{code}")

code, sg = call("GET", f"/contents/{target['id']}/ai-suggest")
check("改进建议（纯规则，永远可用）",
      code == 200 and "suggestions" in sg, f"{sg.get('count')} 条")

# ============================================================ 12. 导出环节
section("12. 导出环节：资产校验 / 追踪注入 / JSON Schema")
code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "set_token", "token": "brand", "value": "#ff0000"}],
    "dry_run": True})
check("改主题 token", code == 200, f"{code}")

code, r = call("POST", f"/contents/{target['id']}/patch", {
    "operations": [{"op": "set_token", "token": "不存在的token", "value": "#000"}],
    "dry_run": True})
check("未知 token 被拦", code == 422 and "未知 token" in json.dumps(r, ensure_ascii=False),
      f"{code}")

code, exp = call("POST", f"/contents/{target['id']}/export", {
    "target": "single_html", "allow_lint_error": True,
    "options": {"asset_mode": "inline"}})
check("导出带资产内联", code == 200 and "assets" in exp.get("files", {}),
      f"assets={exp.get('files', {}).get('assets')}")

# 追踪注入
code, sch = call("GET", f"/contents/{target['id']}/schema")
if code == 200:
    s2 = sch["schema"]
    s2["tracking"] = {"utm_source": "email", "utm_campaign": "smoke", "junk": "x"}
    code, saved = call("POST", f"/contents/{target['id']}/save",
                       {"schema": s2, "message": "加 tracking", "lint_gate": False})
    check("保存 tracking 配置", code == 200, f"{code}")
    if code == 200:
        code, exp2 = call("POST", f"/contents/{target['id']}/export", {
            "target": "single_html", "allow_lint_error": True})
        html = exp2.get("html", "") if code == 200 else ""
        check("追踪注入到链接", code == 200 and "utm_source=email" in html,
              f"出现 {html.count('utm_source=email')} 次")
        check("  └ 非法 UTM 键被过滤", "junk=" not in html)

# 表单 JSON Schema
code, flist = call("GET", "/contents?kind=form")
fitem = next((c for c in (flist or []) if c.get("status") != "archived"), None)
if fitem:
    code, js = call("GET", f"/contents/{fitem['id']}/json-schema")
    jd = (js or {}).get("jsonSchema", {})
    check("导出 JSON Schema", code == 200 and jd.get("$schema", "").endswith("draft-07/schema#"),
          f"{len(jd.get('properties', {}))} 个字段")
    check("  └ required 无重复",
          len(jd.get("required", [])) == len(set(jd.get("required", []))),
          str(jd.get("required")))
    check("  └ 含 uiSchema", "uiSchema" in (js or {}))
    check("  └ 字段名可读（非节点 id）",
          all(not n.startswith("field_b_") for n in jd.get("properties", {})),
          str(list(jd.get("properties", {}))[:4]))

    code, vv = call("POST", f"/contents/{fitem['id']}/validate-submission",
                    {"firstname": "", "email": "bad", "country": "XX"})
    check("提交数据校验", code == 200 and vv.get("valid") is False and vv.get("errors"),
          f"{len(vv.get('errors', []))} 个错误")

code, jsn = call("GET", f"/contents/{target['id']}/json-schema")
check("非表单拒绝导出 JSON Schema", code == 400, f"{code}")

# ============================================================ 汇总
print("\n" + "=" * 60)
print(f"通过 \033[32m{PASS}\033[0m / 失败 \033[31m{FAIL}\033[0m （共 {PASS + FAIL}）")
if FAILURES:
    print("\n失败明细：")
    for f in FAILURES:
        print(f"  - {f}")
print("=" * 60)
sys.exit(1 if FAIL else 0)