# Map Link backend engineering audit

Date: 2026-10-29

## 1. Project overview and review scope

The repository is a Python 3.14 FastAPI application. Synchronous SQLAlchemy sessions persist users, settings, reports, conversations, membership, messages, and JWT revocations in PostgreSQL. Argon2 hashes passwords; PyJWT issues access and refresh credentials. Authentication accepts bearer tokens and HttpOnly cookies. A WebSocket endpoint uses Redis GEO indexes to return nearby users and cached reports. Alembic contains five sequential migrations. A standalone script seeds demonstration accounts, conversations, reports, and Redis data.

Reviewed all application modules, request/response schemas, ORM models, migration sources and environment, the seeder, dependency manifest and lockfile, Compose configuration, environment example, and README. Traced registration/login/refresh/logout, request authentication, privacy updates, report ownership and caching, conversation authorization and messaging, WebSocket authentication/location/cleanup, and repeated seeding.

There were no existing tests or pytest configuration. Existing Ruff lint and formatting checks passed before application changes. No separate type checker or CI workflow was present. The working tree was initially clean.

## 2. Issues discovered and status

Locations below refer to the final source tree. Severity describes the potential impact of the original behavior; it does not imply production exploitation.

| Severity | Location | Problem and potential impact | Status |
| --- | --- | --- | --- |
| High | `app/api/v1/auth.py:244` | A concurrent logout could cause one duplicate JTI insert to roll back every revocation in the request, leaving the refresh credential usable while reporting success. | Fixed: isolate each insert in a savepoint, count successful insertions, and rethrow integrity failures that are not an existing-JTI collision. Regression simulates a competing committed revocation. |
| High | `app/api/v1/users.py:60` | WebSocket handshakes did not check browser Origin. HTTP CORS alone did not protect this cookie-authenticated endpoint against unapproved browser origins where cookies are sent. | Fixed: enforce the configured exact origin list before accepting; clients without an Origin header remain supported. |
| High | `app/api/v1/users.py:108` | An established connection retained initial authentication and privacy state. Expired/revoked tokens and changes to `hide_me` did not take effect on subsequent location updates. | Fixed: revalidate the token, active user, and current database settings before processing each valid location update. |
| Medium | `app/api/v1/users.py:69,108` | Synchronous database and Redis-cache work ran directly on the async WebSocket event loop, potentially stalling other connections. | Fixed: execute authentication/settings/cache work in the thread pool. |
| Medium | `app/core/security.py:45,62` | JWT decoding did not require expiration. Malformed subject/JTI values could reach UUID parsing or SQL and raise server errors. | Fixed: require the claims issued by this application and validate subject/JTI types before database use. Invalid credentials return 401. |
| Medium | `app/api/v1/users.py:88` | Malformed JSON escaped the validation handler and terminated the connection. | Fixed: return a validation error and continue accepting location updates. Validation errors also omit arbitrary exception context. |
| Medium | `app/api/v1/users.py:209,238` | Valid JSON with a non-object top-level value crashed user-cache parsing or leaked non-report values into nearby report results. | Fixed: skip non-object user entries and remove invalid/stale report index members. |
| Medium | `app/api/v1/users.py:151` | Failure while removing the user's location skipped Redis connection closure. | Fixed: always attempt `aclose()` in a nested `finally`. |
| Medium | `app/core/redis.py:8,17` | Redis connections and commands had no explicit socket deadlines; unavailable caches could hold API workers or WebSocket operations. | Fixed: two-second connection and socket timeouts for both client factories. Retries may extend the total operation duration. |
| Medium | `app/core/settings.py:41`; `alembic/env.py:12` | URL-special characters in database credentials changed URL parsing; encoded percent signs also conflicted with Alembic configuration interpolation. | Fixed: construct the URL with SQLAlchemy and escape percent signs for Alembic. Verified by unit test and actual offline SQL generation with special-character credentials. |
| Medium | `app/api/v1/conversations.py:144` | Negative limit/offset values could produce database errors or bypass the intended message-count cap on some backends. | Fixed: require positive limits and nonnegative offsets; keep the existing 100-message cap. |
| Medium | `app/api/v1/users.py:30` | Latitude values accepted by validation exceeded Redis GEO's supported range and could fail during map operations. | Fixed: validate the supported range before issuing GEO commands. Report persistence keeps its existing geographic validation. |
| Low | `scripts/seed_demo.py:242` | Seeded read markers used message IDs before SQLAlchemy generated them, storing null instead of the last message. | Fixed: flush before assigning the read marker. |
| Medium | `app/core/user_cache.py:17` | Concurrent requests creating missing legacy settings could hit the unique constraint and leave a failed session. | Fixed: use a savepoint and re-read the winning row; unrelated integrity errors still propagate. A stale-read regression confirms session usability after the collision. |
| Low | `app/api/v1/user_settings.py:15,23` | Settings lookup/creation duplicated the implementation in user caching. | Refactored: use the existing shared helper. |
| Low | `app/core/user_cache.py:66`; `app/api/v1/reports.py:42,99` | Broad cache exception handlers also suppressed programming errors. | Fixed: catch Redis errors specifically while preserving nonfatal handling of actual Redis outages. |
| Medium | `README.md:68,93` | The environment instructions advertised an unsupported `ALLOWED_ORIGIN_REGEX` setting, which could also cause settings validation to reject a copied `.env`. | Corrected documentation to use the supported explicit origin list. |

Redis's supported latitude bounds were checked against its [official GEOADD documentation](https://redis.io/docs/latest/commands/geoadd/).

## 3. Changes implemented and compatibility

Added a development dependency group for pytest and pytest-cov, locked its dependencies, configured complete application/seeder line coverage with an 85% minimum, and added six test/support files. Generated test, coverage, and Ruff artifacts are ignored by Git. README now explains execution, isolation, origin configuration, token revalidation, and coordinate validation.

Changes retain the existing routes, successful response shapes, ORM models, migration definitions, report ownership rules, message privacy rules, and report cache lifetimes. No schema, production infrastructure, or product feature was added. Necessary changes to invalid-input handling are explicit: nonpositive message limits and negative offsets return 422; unsupported WebSocket latitudes return a validation error; missing required JWT claims are rejected; unapproved browser origins are denied. Existing valid tokens already carry the required claims.

WebSocket revalidation adds database and cache work per valid update. This prioritizes correctness of authentication and privacy; throughput under realistic concurrent traffic has not been benchmarked. Connections are revalidated when processing an update, rather than proactively closed by a background expiry timer.

## 4. Testing and validation

Final complete run on CPython 3.14.3:

```text
.venv/bin/pytest -q --cov-report=xml:/tmp/map-link-coverage.xml
51 passed, 2 warnings in 4.08s
98.81% line coverage: 911 of 922 statements covered
Required coverage threshold: 85%
```

Coverage includes every Python module under `app/` and `scripts/`, including models and the demo seeder. No application or seeder modules are omitted. Historical Alembic migration scripts and tests are outside that coverage denominator. This is line coverage, not branch coverage or a claim that all concurrency schedules have been exercised.

The initial regression batch produced 17 failures and one pass before fixes. Additional regression checks demonstrated the logout conflict and out-of-range location behaviors before their fixes. The full suite then verified:

- Unit behavior: password hashing, credential parsing and JWT claims, database URL escaping, cache decoding and filtering, cache error handling, Redis deadlines, recovery from a conflicting settings insert, and session/client cleanup.
- In-process integration: registration, cookie and bearer login, refresh, revocation, inactive/admin checks, settings creation and updates, report creation/deletion/ownership, conversation creation and reuse, membership authorization, messaging, pagination, read markers, and cross-conversation read rejection.
- WebSockets: denied origins, unauthorized and revoked credentials, privacy changes, bad JSON, invalid shapes and coordinates, nearby-map responses, and resource cleanup.
- Seeder integration: repeated runs preserve account IDs without duplicating reports/messages, foreign-key cascades remove old data, hidden users are not published, read markers reference real messages, and failures roll back and close sessions.

SQLite tests enable foreign keys and isolate each test in a fresh database. Redis is mocked. WebSocket database sessions are redirected to the test engine. Tests do not depend on live services or production credentials. Sandboxed TestClient execution hung on event-loop socket restrictions, so the successful runs used the approved execution path outside that sandbox.

Other executed checks:

| Check | Result |
| --- | --- |
| `.venv/bin/ruff check .` | Passed |
| `.venv/bin/ruff format --check .` | Passed |
| `git diff --check` | Passed |
| `uv lock --check` | Passed; 58 resolved packages |
| Import `app.main` and generate OpenAPI using explicit test settings | Passed |
| `alembic upgrade head --sql` with special-character test credentials | Passed through all five revisions; output at `/tmp/map-link-migrations.sql` |

The two warnings are upstream deprecations: AnyIO's pytest plugin uses a pytest alias scheduled for removal, and Starlette recommends a successor to its current httpx TestClient transport. No tests or warnings were disabled to obtain a passing result.

Remaining uncovered lines are the registration integrity-conflict handler, an unrecognized logout token type, propagation of a nonduplicate revocation integrity error, a defensive missing-membership branch, malformed UUID parsing, propagation of an unrelated settings integrity error, and the seeder's direct-script/import-path entry points. The critical observed bugs have regression coverage; low-frequency guards remain in this line-coverage gap.

Real PostgreSQL migrations, downgrade/re-upgrade behavior, real Redis command semantics, network timeouts under packet loss, and multiworker concurrency were not executed. Docker daemon access was unavailable to the sandbox. Offline migration generation validates SQL generation and credential interpolation, not successful database execution. No dependency vulnerability scanner was configured or run.

## 5. Remaining findings and recommendations

These are unresolved observations or review-derived risks. They are separate from completed fixes and have not been presented as proven production incidents.

| Severity | Location | Remaining concern and next step |
| --- | --- | --- |
| Medium | `app/api/v1/conversations.py:57,245` | Concurrent requests can both see no direct conversation and create separate conversations for the same pair. Select a concurrency strategy and validate it against PostgreSQL; a pair uniqueness constraint would require schema approval. |
| Medium | `app/api/v1/users.py:119,151` | Locations are indexed per user, not connection. Closing one of several connections removes that user's location even if another connection remains active. Process crashes can also leave stale locations until cache expiry/filtering. Connection ownership or heartbeat semantics need an explicit lifecycle decision. |
| Medium | `app/api/v1/reports.py:50,107` | PostgreSQL commits and Redis changes are separate operations. A failed cache deletion can leave a deleted report visible until its three-hour TTL. Select reconciliation/retry semantics before introducing durable cross-service coordination. |
| Medium | `scripts/seed_demo.py:180,258` | Seeding deletes conversations involving demo accounts and clears all report/location cache entries, including unrelated data. Existing behavior is preserved; run only against a dedicated demo database and Redis instance. Changing cleanup ownership requires defining what demo data may be shared. |
| Medium | `alembic/versions/8489b5758f6b_base_migration.py:84` | The base downgrade drops user tables but does not explicitly remove the PostgreSQL `user_role` enum. Review and test downgrade/re-upgrade against a disposable PostgreSQL database before changing historical migration behavior. |
| Low | `app/api/v1/conversations.py:120,319` | Conversation listing makes per-conversation membership and last-message queries and has no pagination. Measure actual workloads before choosing batching or an API pagination contract. |
| Low | `app/api/v1/conversations.py:158,345` | Timestamp-only ordering does not define a tie breaker for equal timestamps. Agree on ordering semantics before changing message pagination or last-message selection. |
| Low | `app/api/v1/schemas/user.py`; `app/api/v1/auth.py:277` | Registration permits empty identity fields and usernames that overlap another user's email. Login searches both email and username. Establish identity-validation and collision rules before tightening the public registration contract. |
| Low | `app/api/v1/schemas/report.py`; `app/api/v1/reports.py:50` | Report storage accepts polar coordinates that Redis cannot index. Report persistence behavior is preserved; deciding whether to reject those reports or return partial map coverage is a product/API decision. |

Prioritize a disposable PostgreSQL/Redis integration job, migration round-trip tests, and concurrency tests before production rollout. Deployment configuration should also validate the intended JWT secret, HTTPS cookie flags, and frontend origins. No production configuration or external service was changed during this audit.
