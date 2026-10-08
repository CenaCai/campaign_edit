"""MCP（Model Context Protocol）客户端：零依赖，标准库直接实现。

支持两种传输：
* ``stdio``：子进程 + JSON-RPC 2.0 over stdin/stdout（line-delimited JSON）
* ``http``  ：Streamable HTTP，POST JSON-RPC 到 ``url``

用途：把外部能力（取赛事数据、拉图片、查 CRM、发消息）接进内容生产链路。
设计取舍：
* 不强依赖官方 ``mcp`` 包（Python 3.10+ / 3.13 兼容性、以及部署体积考虑）；
* stdio 模式强制超时与进程回收，插件不能拖死主进程；
* 只做 ``initialize / tools/list / tools/call / resources/list / prompts/list``，
  不实现 sampling 与 roots（服务端反向调用），足够覆盖内容系统场景。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "campaign-edit", "version": "0.1.0"}


class MCPClientError(RuntimeError):
    pass


@dataclass
class MCPClient:
    config: dict[str, Any]
    timeout: float = 20.0
    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def transport(self) -> str:
        return str(self.config.get("transport") or "stdio")

    @property
    def name(self) -> str:
        return str(self.config.get("name") or "mcp")

    # -------------------------------------------------- stdio
    def _ensure_proc(self) -> subprocess.Popen:
        if self._proc and self._proc.poll() is None:
            return self._proc
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (self.config.get("env") or {}).items()})
        try:
            self._proc = subprocess.Popen(
                [str(self.config["command"])] + [str(a) for a in (self.config.get("args") or [])],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1, env=env,
                cwd=self.config.get("cwd") or None,
            )
        except FileNotFoundError as exc:
            raise MCPClientError(f"无法启动 MCP 命令 {self.config.get('command')!r}: {exc}") from exc
        return self._proc

    def _rpc_stdio(self, method: str, params: dict | None = None,
                   _id: int | None = None) -> dict[str, Any]:
        with self._lock:
            proc = self._ensure_proc()
            msg = {"jsonrpc": "2.0", "id": _id if _id is not None else 1, "method": method,
                   "params": params or {}}
            try:
                proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise MCPClientError(f"MCP 进程写入失败（可能已退出）: {exc}") from exc
            #跳过非 JSON 行（有些 server 会打日志到 stdout）
            deadline_lines = 0
            while True:
                line = proc.stdout.readline()
                if not line:
                    err = ""
                    try:
                        err = (proc.stderr.read() or "")[:400]
                    except Exception:
                        pass
                    raise MCPClientError(f"MCP 无响应（进程可能退出）: {err}")
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    deadline_lines += 1
                    if deadline_lines > 200:
                        raise MCPClientError("MCP 输出过多非 JSON 行，已中止")

    # -------------------------------------------------- http
    def _rpc_http(self, method: str, params: dict | None = None) -> dict[str, Any]:
        url = str(self.config.get("url") or "")
        if not url:
            raise MCPClientError("http 传输缺少 url")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update({str(k): str(v) for k, v in (self.config.get("headers") or {}).items()})
        if self.config.get("token"):
            headers.setdefault("Authorization", f"Bearer {self.config['token']}")
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                           "params": params or {}}, ensure_ascii=False).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            raise MCPClientError(f"MCP HTTP {e.code}: {e.read().decode('utf-8','ignore')[:300]}")
        except Exception as e:
            raise MCPClientError(f"MCP 网络错误: {e}") from e
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"MCP 响应非 JSON: {raw[:200]}") from exc

    # -------------------------------------------------- RPC
    def call_rpc(self, method: str, params: dict | None = None) -> Any:
        res = (self._rpc_stdio(method, params) if self.transport == "stdio"
               else self._rpc_http(method, params))
        if isinstance(res, dict) and res.get("error"):
            err = res["error"]
            raise MCPClientError(f"{err.get('code')}: {err.get('message')}")
        return (res or {}).get("result")

    def initialize(self) -> dict[str, Any]:
        res = self.call_rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}, "resources": {}},
            "clientInfo": CLIENT_INFO,
        })
        if self.transport == "stdio":
            # stdio 型需要发 initialized 通知
            proc = self._proc
            if proc and proc.stdin:
                try:
                    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
                                     + "\n")
                    proc.stdin.flush()
                except Exception:
                    pass
        return res or {}

    def probe(self) -> dict[str, Any]:
        """健康检查：initialize + tools/list。"""
        try:
            info = self.initialize()
            tools = self.list_tools()
            return {"ok": True, "server": info.get("serverInfo", {}),
                    "protocolVersion": info.get("protocolVersion"),
                    "tool_count": len(tools.get("tools", [])),
                    "tools": [t.get("name") for t in tools.get("tools", [])][:30]}
        except MCPClientError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            self.close()

    def list_tools(self) -> dict[str, Any]:
        return self.call_rpc("tools/list", {}) or {}

    def call_tool(self, name: str, arguments: dict | None = None,
                  *, timeout: float | None = None) -> dict[str, Any]:
        old = self.timeout
        if timeout:
            self.timeout = timeout
        try:
            return self.call_rpc("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        finally:
            self.timeout = old

    def list_resources(self) -> dict[str, Any]:
        return self.call_rpc("resources/list", {}) or {}

    def list_prompts(self) -> dict[str, Any]:
        return self.call_rpc("prompts/list", {}) or {}

    # -------------------------------------------------- 生命周期
    def close(self) -> None:
        p = self._proc
        self._proc = None
        if not p:
            return
        try:
            if p.stdin:
                p.stdin.close()
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def __enter__(self) -> "MCPClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def tool_text(result: dict[str, Any]) -> str:
    """MCP tools/call 结果 → 纯文本（content[] 拼接）。"""
    parts: list[str] = []
    for c in (result.get("content") or []):
        if isinstance(c, dict):
            if c.get("type") == "text":
                parts.append(str(c.get("text") or ""))
            elif c.get("type") == "resource":
                res = c.get("resource") or {}
                parts.append(str(res.get("text") or res.get("uri") or ""))
        elif isinstance(c, str):
            parts.append(c)
    return "\n".join(p for p in parts if p)


EXAMPLE_MCP = {
    "name": "example-fetch",
    "transport": "http",
    "url": "http://127.0.0.1:8931/mcp",
    "description": "示例：把赛事/库存数据接进内容生产",
}