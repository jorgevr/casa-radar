"""Minimal stdio MCP server used to test our client: answers initialize, tools/list, tools/call."""
import json
import sys

ADS = {"elementList": [
    {"propertyCode": "A1", "price": 420000, "size": 160, "rooms": 4, "bathrooms": 3, "propertyType": "chalet",
     "latitude": 40.34, "longitude": -3.83, "municipality": "Alcorcón", "neighborhood": "Prado Santo Domingo",
     "url": "https://example.test/a1"},
]}

for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue  # notification
    m = msg["method"]
    if m == "initialize":
        res = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake"}}
    elif m == "tools/list":
        res = {"tools": [{"name": "search_ads", "inputSchema": {"type": "object"}}]}
    elif m == "tools/call":
        if msg["params"]["arguments"].get("fail"):
            res = {"isError": True, "content": [{"type": "text", "text": "missing credentials"}]}
        else:
            res = {"content": [{"type": "text", "text": json.dumps(ADS)}]}
    else:
        res = {}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
