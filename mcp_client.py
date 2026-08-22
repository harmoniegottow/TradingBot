#!/usr/bin/env python3
"""cTrader Remote MCP - minimaler Testclient (StreamableHTTP, ohne SDK).

Liest den Bearer-Slug aus /opt/data/.secrets/ctrader_mcp_token.txt.
Der Token darf NIE inline in eine Shell-Zeile geschrieben werden.
"""
import json
import sys
import urllib.error
import urllib.request

TOKEN_PATH = "/opt/data/.secrets/ctrader_mcp_token.txt"
URL = "https://mcp.ctrader.com/trading/mcp"


def token():
    with open(TOKEN_PATH) as fh:
        return fh.read().strip()


class Client:
    def __init__(self):
        self.session = None
        self.tok = token()
        self._id = 0

    def _headers(self):
        h = {
            "Authorization": "Bearer " + self.tok,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            h["Mcp-Session-Id"] = self.session
        return h

    def _post(self, payload, want_response=True):
        req = urllib.request.Request(
            URL, data=json.dumps(payload).encode(), headers=self._headers()
        )
        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}"
            ) from None
        if self.session is None:
            self.session = resp.headers.get("Mcp-Session-Id")
        raw = resp.read().decode(errors="replace")
        if not want_response:
            return None
        out = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                out = json.loads(line[5:].strip())
        return out if out is not None else (json.loads(raw) if raw.strip() else None)

    def rpc(self, method, params=None):
        self._id += 1
        res = self._post(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        )
        if res and "error" in res:
            raise RuntimeError(f"{method} -> {res['error']}")
        return (res or {}).get("result")

    def connect(self):
        info = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "hermes-tradingbot", "version": "1.0"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, False)
        return info

    def tools(self):
        return self.rpc("tools/list")["tools"]

    def call(self, name, args=None):
        return self.rpc("tools/call", {"name": name, "arguments": args or {}})


def main():
    cli = Client()
    info = cli.connect()
    srv = info.get("serverInfo", {})
    print(f"Server : {srv.get('name')} v{srv.get('version')}")
    print(f"Session: {cli.session}")

    if len(sys.argv) > 1 and sys.argv[1] == "instructions":
        print(info.get("instructions", ""))
        return

    if len(sys.argv) > 2 and sys.argv[1] == "call":
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        res = cli.call(sys.argv[2], args)
        for item in res.get("content", []):
            print(item.get("text", item))
        if res.get("isError"):
            print("[TOOL ERROR]")
        return

    tools = cli.tools()
    print(f"\n{len(tools)} Werkzeuge:\n")
    for tool in tools:
        schema = tool.get("inputSchema", {})
        req = ",".join(schema.get("required", []))
        head = (tool.get("description") or "").strip().split("\n")[0]
        print(f"  {tool['name']}")
        print(f"    pflicht: {req or '-'}")
        print(f"    {head[:160]}")


if __name__ == "__main__":
    main()
