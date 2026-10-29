# Known Limitations

Current as of Phase 1 (2026-10-29).

## Functional
- No authentication yet. All endpoints are public; only health endpoints exist. Do not expose a deployment beyond localhost until Phase 2 lands.
- No domain features (leads, research, scoring, agents, outreach). The Overview shows an empty state rather than placeholder numbers.
- Sidebar entries for unbuilt modules are non-interactive and labelled with their delivery phase.

## Operational
- GitHub Actions workflow is written but has not run; no remote repository is configured.
- Nothing is committed yet; the repository was initialized but the first commit awaits review.
- No background worker, rate limiting, OpenTelemetry export, or error-monitoring integration yet (planned Phases 2, 6, 11).
- `make` is unavailable in plain PowerShell; use Git Bash/WSL or the raw commands in README.

## Tooling
- `pnpm` reports `eslint@9` as deprecated; `eslint-config-next@16.4.3` is validated against ESLint 9, so the upgrade to 10 is deferred.
- Starlette's TestClient emits a deprecation warning about `httpx`; it is filtered in pytest config until FastAPI's test client migrates.
