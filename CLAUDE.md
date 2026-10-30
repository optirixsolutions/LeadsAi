# SalesIQ — working notes for Claude Code

Evidence-driven revenue intelligence SaaS. Monorepo: FastAPI API + Next.js web.
Start every session by reading `docs/IMPLEMENTATION_ROADMAP.md` (current phase, next steps).

## Layout
- `apps/api` — FastAPI, SQLAlchemy 2, Alembic, psycopg 3. Python 3.12, managed by `uv`.
- `apps/web` — Next.js App Router, React 19, Tailwind v4, strict TS. Managed by `pnpm`.
- `packages/contracts` — TS types generated from the API OpenAPI schema. Never hand-edit `src/openapi.ts`.
- `docs/` — spec, architecture, data model, API, security, decisions, limitations.

## Commands (run from repo root unless noted)
- Infra: `docker compose up -d --wait postgres redis` (host ports 55432 / 56379)
- API (in `apps/api`): `uv run alembic upgrade head`, `uv run uvicorn app.main:app --reload --port 8000`
- Worker (in `apps/api`): `uv run python -m app.tasks.worker`. Workflows, briefs, and large imports wait for it.
- API checks (in `apps/api`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
- Web: `pnpm --filter @salesiq/web dev|lint|typecheck|test|build|test:e2e`
- Contracts: `pnpm contracts:generate` after any API schema change; CI fails if stale.

## Rules specific to this repo
- Tenant context comes from the authenticated server-side identity, never from client input.
- Every error response uses the envelope in `apps/api/app/core/errors.py`.
- New tables: add the model, then `uv run alembic revision --autogenerate`, review it, and keep `tests/test_migrations.py` green.
- Tests hit only the `salesiq_test` database (enforced in `tests/conftest.py`).
- UI: no hardcoded metrics, no dead controls. Unbuilt pages are non-link nav items tagged with their phase.
- No real emails, paid model calls, or external mutations without explicit approval.
- No mock model providers. AI work runs on real local models (Ollama, open models from Hugging Face); see `apps/api/app/agents/llm/models.yaml`. Test failure paths with real failures, such as a closed port or a missing model.
- Record architecture decisions in `docs/DECISIONS.md`; record gaps in `docs/KNOWN_LIMITATIONS.md`.
