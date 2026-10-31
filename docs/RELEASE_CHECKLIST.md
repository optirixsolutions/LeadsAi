# Release checklist

Status of each release requirement, from what was actually run on 2026-10-31 on one Windows development machine. **Not released, and not deployed anywhere.** "Done" means it was run and passed. "Not done" says what it needs.

## Verdict
Ready for a staging deployment by someone who supplies the items under "Needs the owner". Not ready for real customers until those are done, in particular a real mail provider test and a first CI run.

## Requirements
| Requirement | Result | Evidence |
|---|---|---|
| Full tests | Done | See the tests table in IMPLEMENTATION_ROADMAP.md |
| Security issues fixed | Done, with listed gaps | Independent reviews in Phases 2, 5, 6, 7, 8, and 10. Remaining items are in KNOWN_LIMITATIONS.md. No review covered the whole product at once |
| Dependency checks | Done | `pip-audit` and `pnpm audit --prod`: no known vulnerabilities on this date |
| Database migrations | Done | 12 revisions apply to an empty database in a container, as a one-off job. `tests/test_migrations.py` covers the rest. No upgrade has been tried on a large database |
| Clean installation | Done, partly | A fresh `git clone` installs from lockfiles, imports, type-checks, and builds. The README's quick start was not followed by a person, and `.env.example` could not be read in this environment (see below) |
| Production build | Done | All images built, and run as a non-root user |
| Containers | Done | Full stack from an empty volume: API, web, worker, MCP, Postgres, Redis |
| End to end, in containers | Done | `scripts/release_smoke.py` through the web address: account, lead, evidence, a real model through the container worker, approval, a refused send, usage, analytics, and MCP with a token |
| Backups and recovery | Done once | `pg_dump` and `pg_restore` drill on a small database. Counts, RLS, policies, and role limits matched. Not on managed Postgres, and not with file or key recovery |
| Startup refuses unsafe config | Done | In the production image: default secret, missing credentials key, and sending without a public HTTPS address are all refused |
| Security headers | Done, partly | CSP checked in the production image, and with a browser under it. `__Host-` cookies are tested at the API, but no browser has used them, because that needs real HTTPS. CSP allows inline scripts, because of Next's bootstrap |
| Performance | Done, in one setting | `scripts/load_check.py`, 50,000 leads, on this machine in Docker. See below. Not a production capacity estimate |
| Deployment docs | Done | DEPLOYMENT.md. The procedure has not been carried out on a real platform |
| Known limitations | Done | KNOWN_LIMITATIONS.md |

## Measured with 50,000 leads
Five samples each, on the container stack, from a single client.

| Path | Median | Worst |
|---|---|---|
| Leads, first page | 61 ms | 75 ms |
| Leads, search | 143 ms | 167 ms |
| Leads, not scored yet | 71 ms | 74 ms |
| Analytics, 90 days | 75 ms | 83 ms |
| Overview analytics | 39 ms | 81 ms |
| What is waiting | 23 ms | 36 ms |
| Usage | 31 ms | 32 ms |
| Drafts | 19 ms | 20 ms |

With 10 clients at once on the leads page: 61 requests per second, 151 ms median, 220 ms worst. With 25: 54 requests per second, 405 ms median, 724 ms worst. The API ran as one process. These seeded rows have no assessments, so the fit figures are a best case, and no model calls or writes were included.

## Needs the owner
None of these can be done from here without a decision or something only the owner has.

1. **A remote repository.** CI has never run. Everything above ran on one Windows machine, and the CI workflow's Linux environment is untested.
2. **A real email provider,** its credentials, a verified sending domain with SPF and DKIM, and approval to send. STARTTLS, provider login, and external delivery have never run against a real server.
3. **A hosting choice,** with managed Postgres and backups, TLS, real secrets, and forwarded-address configuration. The restore drill should be repeated there.
4. **A payment provider,** if plans are to be sold. Until then, every organization stays on the default plan.
5. **Update `.env.example`** with `SALESIQ_CREDENTIALS_KEY`, `SALESIQ_DEFAULT_PLAN`, and the `SALESIQ_DISPATCH_*` settings from DEPLOYMENT.md. A local rule blocks reading that file here, so it may be out of date.
6. **A legal review** of outreach: consent, regional email law, and what the opt-out and postal address need to say.
7. **Human ratings of model output.** Every AI result here is measured on small, fictional data, with planted-instruction attacks reaching drafts. Real use needs real evaluation.

## Not run
- Colab paths in the notebooks, and the hosted Hugging Face route.
- The research fetcher against the public internet.
- A browser other than Chromium, and any screen reader.
- A person using the product. All journeys were driven by automated tests.
