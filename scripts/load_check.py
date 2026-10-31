"""Measure the read paths on a large organization, against a disposable deployment.

    python scripts/load_check.py http://127.0.0.1:8019 salesiq-release [leads]

Creates its own account, seeds fictional rows directly through `docker compose exec`, and prints
timings. It refuses nothing by itself, so never point it at a database that matters.
"""

import http.cookiejar
import json
import secrets
import statistics
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API, PROJECT = sys.argv[1], sys.argv[2]
LEADS = int(sys.argv[3]) if len(sys.argv) > 3 else 50_000
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(method: str, path: str, body: object = None) -> dict:
    csrf = next((c.value for c in jar if c.name == "salesiq_csrf"), None)
    headers = {"content-type": "application/json", **({"x-csrf-token": csrf} if csrf else {})}
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{API}/api/v1{path}", data, headers, method=method)
    with opener.open(request, timeout=120) as response:
        text = response.read().decode()
    return json.loads(text) if text else {}


def sql(statement: str) -> str:
    command = ["docker", "compose", "-p", PROJECT, "exec", "-T", "postgres", "psql", "-U", "salesiq"]
    done = subprocess.run(
        [*command, "-d", "salesiq", "-v", "ON_ERROR_STOP=1", "-At", "-c", statement],
        capture_output=True,
        text=True,
    )
    if done.returncode:
        sys.exit(done.stderr[:500])
    return done.stdout.strip()


email = f"load-{secrets.token_hex(4)}@example.com"
call("POST", "/auth/register", {"email": email, "password": secrets.token_urlsafe(24)})
org = call("POST", "/organizations", {"name": f"Load {secrets.token_hex(3)}"})["id"]
base = f"/organizations/{org}"

started = time.perf_counter()
sql(f"""
INSERT INTO leads (id, organization_id, status, first_name, email, created_at, updated_at, tags, custom_fields)
SELECT gen_random_uuid(), '{org}', 'new', 'Lead' || n, 'lead' || n || '@example.com',
       now() - (n % 90) * interval '1 day', now(), '{{}}', '{{}}'
FROM generate_series(1, {LEADS}) n;
""")
print(f"seeded {LEADS:,} leads in {time.perf_counter() - started:.1f} s", flush=True)
PATHS = {
    "leads, first page": f"{base}/leads?limit=50",
    "leads, search": f"{base}/leads?q=lead4999&limit=50",
    "leads, not scored": f"{base}/leads?fit=none&limit=50",
    "analytics, 90 days": f"{base}/analytics/report?days=90",
    "analytics overview": f"{base}/analytics/overview",
    "attention": f"{base}/analytics/attention",
    "usage": f"{base}/usage",
    "drafts": f"{base}/outreach/drafts",
}


def timed(path: str) -> float:
    begun = time.perf_counter()
    call("GET", path)
    return (time.perf_counter() - begun) * 1000


print(f"{'path':24} {'median ms':>10} {'worst ms':>10}", flush=True)
for name, path in PATHS.items():
    samples = [timed(path) for _ in range(5)]
    print(f"{name:24} {statistics.median(samples):10.0f} {max(samples):10.0f}", flush=True)

for workers in (10, 25):
    begun = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        samples = list(pool.map(timed, [PATHS["leads, first page"]] * workers * 4))
    took = time.perf_counter() - begun
    print(
        f"{workers} at once on the leads page: {len(samples) / took:.0f} requests/s, "
        f"median {statistics.median(samples):.0f} ms, worst {max(samples):.0f} ms",
        flush=True,
    )
