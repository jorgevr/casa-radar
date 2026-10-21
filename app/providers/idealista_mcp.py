"""Idealista via the `galimru/idealista-mcp` server, spoken to over stdio JSON-RPC.

Needs the idealista-mcp binary plus the OAuth client_key / client_secret / signing_secret that Idealista
issues for its API (see that repo's README, config at ~/.config/idealista-mcp/config.json). Without them
the server starts but every tool call fails — this module surfaces that error verbatim.

What I could verify: the server exposes `search_locations` (prefix -> location ids) and `search_ads`
(location_id OR center+distance, plus filters). I could not read the exact argument names or the response
shape, so:
  * run `python -m app.cli mcp-schema` once to print the real tool schemas;
  * put the argument names that schema shows in `config/providers.yaml` -> idealista.search_args;
  * the response parser below is deliberately tolerant (it looks for a list of ads under several usual keys),
    and raises with the raw payload if it can't find one, instead of guessing.
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading

from ..listings import upsert_listing


class McpError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(self, cmd: list[str], timeout: float = 90.0):
        self.timeout = timeout
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1)
        self._q: queue.Queue = queue.Queue()
        self._id = 0
        threading.Thread(target=self._reader, daemon=True).start()
        self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "casa-radar", "version": "0.1"}})
        self._notify("notifications/initialized")

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line:
                try:
                    self._q.put(json.loads(line))
                except json.JSONDecodeError:
                    pass
        self._q.put(None)

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def _request(self, method, params=None):
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            try:
                msg = self._q.get(timeout=self.timeout)
            except queue.Empty:
                raise McpError(f"timeout waiting for {method}") from None
            if msg is None:
                err = self.proc.stderr.read() if self.proc.stderr else ""
                raise McpError(f"MCP server exited. stderr: {err[:500]}")
            if msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(f"{method}: {msg['error']}")
                return msg.get("result")

    def list_tools(self):
        return self._request("tools/list").get("tools", [])

    def call(self, name: str, arguments: dict):
        res = self._request("tools/call", {"name": name, "arguments": arguments})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise McpError(text or "tool returned an error")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


_LIST_KEYS = ("elementList", "ads", "items", "results", "properties", "data")


def extract_ads(payload) -> list[dict]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for k in _LIST_KEYS:
            if isinstance(payload.get(k), list):
                return [p for p in payload[k] if isinstance(p, dict)]
        for v in payload.values():  # one level down, e.g. {"result": {"ads": [...]}}
            if isinstance(v, dict):
                for k in _LIST_KEYS:
                    if isinstance(v.get(k), list):
                        return [p for p in v[k] if isinstance(p, dict)]
    raise McpError("no ad list found in response; raw payload: " + json.dumps(payload, ensure_ascii=False)[:800])


def search(conn, needs: dict, cmd: list[str], args: dict, tool: str = "search_ads") -> list[str]:
    client = McpStdioClient(cmd)
    try:
        payload = client.call(tool, args)
    finally:
        client.close()
    return [upsert_listing(conn, ad, "idealista", needs) for ad in extract_ads(payload)]


def schema(cmd: list[str]) -> list[dict]:
    client = McpStdioClient(cmd)
    try:
        return client.list_tools()
    finally:
        client.close()
