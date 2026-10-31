"""Walk a running deployment end to end, through its public web address, with a real model.

    python scripts/release_smoke.py http://127.0.0.1:3019 http://127.0.0.1:8119 localhost:8100

Creates its own account and fictional data, so point it only at a disposable deployment. Prints what
it checked, and exits non-zero at the first thing that does not work. It needs only the standard
library, so it can run from anywhere. A model answer can take minutes on a small machine.
"""

import http.cookiejar
import json
import secrets
import sys
import time
import urllib.error
import urllib.request

WEB, MCP, MCP_HOST = sys.argv[1], sys.argv[2], sys.argv[3]
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
NOTE = "Acme employs about 120 people and needs lead scoring this quarter."


def call(method: str, path: str, body: object = None, expect: int = 200) -> dict:
    csrf = next((c.value for c in jar if c.name == "salesiq_csrf"), None)
    headers = {"content-type": "application/json", **({"x-csrf-token": csrf} if csrf else {})}
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{WEB}/api/v1{path}", data, headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            status, text = response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode()
    if status != expect:
        sys.exit(f"FAILED {method} {path}: expected {expect}, got {status}: {text[:300]}")
    return json.loads(text) if text else {}


def ok(message: str) -> None:
    print(f"ok  {message}", flush=True)


email = f"smoke-{secrets.token_hex(4)}@example.com"
password = secrets.token_urlsafe(24)
call("POST", "/auth/register", {"email": email, "password": password, "display_name": "Smoke"}, 201)
org = call("POST", "/organizations", {"name": f"Smoke {secrets.token_hex(3)}"}, 201)["id"]
base = f"/organizations/{org}"
ok("registered and created an organization through the web address")

lead = call(
    "POST",
    f"{base}/leads",
    {"first_name": "Tess", "email": f"tess-{secrets.token_hex(3)}@example.com"},
    201,
)["id"]
call("POST", f"{base}/leads/{lead}/evidence", {"content": NOTE}, 201)
ok("created a lead and evidence")

agent = call("POST", f"{base}/agents/research/runs", {"lead_id": lead}, 202)["id"]
started = time.time()
while True:
    run = call("GET", f"{base}/agent-runs/{agent}")
    if run["status"] != "running":
        break
    if time.time() - started > 480:
        sys.exit("FAILED the worker did not finish an agent run within 8 minutes")
    time.sleep(5)
if run["status"] == "failed":
    sys.exit(f"FAILED the agent run failed: {run['failure_category']}")
if run["tool_call_count"] < 1:
    sys.exit("FAILED the model answered without using a tool")
ok(
    f"container worker ran a real model: {run['status']}, {run['tool_call_count']} tool calls, "
    f"{len(run['claims'])} claims kept, {round(time.time() - started)} s"
)

draft = call(
    "POST",
    f"{base}/outreach/drafts",
    {"lead_id": lead, "subject": "Hello", "body": "A short note."},
    201,
)
draft = call("POST", f"{base}/outreach/drafts/{draft['id']}/request-approval")
call("POST", f"{base}/approvals/{draft['approval']['id']}/approve", {"content_hash": draft["content_hash"]})
refused = call("POST", f"{base}/outreach/drafts/{draft['id']}/send", None, 409)
codes = [d["code"] for d in refused["error"]["details"]]
if "dispatch_disabled" not in codes:
    sys.exit(f"FAILED a send should be refused while sending is off, got {codes}")
ok(f"an approved draft was refused at send, as sending is off by default: {codes}")

usage = {m["metric"]: m["used"] for m in call("GET", f"{base}/usage")["metrics"]}
if usage["monthly_model_tokens"] < 1 or usage["monthly_workflow_runs"] != 1 or usage["leads"] != 1:
    sys.exit(f"FAILED usage does not match what just happened: {usage}")
ok(f"usage matches what just happened: {usage}")
if call("GET", f"{base}/analytics/report?days=7")["leads"]["by_status"] != {"new": 1}:
    sys.exit("FAILED analytics do not match")
ok("analytics match")

token = call("POST", f"{base}/mcp-tokens", {"name": "smoke", "scope": "read"}, 201)["secret"]
init = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "1"},
    },
}
request = urllib.request.Request(
    f"{MCP}/mcp",
    json.dumps(init).encode(),
    {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "host": MCP_HOST,
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=20) as response:
    if response.status != 200 or "SalesIQ" not in response.read().decode().replace("salesiq", "SalesIQ"):
        sys.exit("FAILED the MCP server did not initialize")
ok("the MCP container answered with a real token")
print("all checks passed")
