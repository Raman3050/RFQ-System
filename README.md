# British Auction RFQ System

An RFQ (Request for Quotation) platform with British Auction–style bidding: automatic time
extensions near close, a hard forced-close time, configurable triggers, and live auction progress.

- **Stack:** React + Vite + TypeScript + MUI · FastAPI (Python 3.13) · PostgreSQL 16 · Redis 7

## Project status

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundations: scaffolding, Docker, migrations, health checks, CI | ✅ Done |
| 1 | Auth & users: JWT + rotating refresh cookie, roles, seed data, login/register UI | ✅ Done |
| 2 | RFQ create/edit/cancel, invite-only suppliers via email, listing & details pages | ✅ Done |
| 3 | Bidding engine: bids, L1/L2 ranking, all 3 extension triggers, forced-close cap, activity log | ✅ Done |
| 4 | Lifecycle worker: opens/closes/force-closes auctions on time, records the winner | ✅ Done |
| 5 | Real-time updates (WebSockets + Redis pub/sub), winner email on close | ✅ Done |
| 6 | Hardening: rate limiting, security headers, production images behind Nginx, load test | ✅ Done |
| 7 | Success metrics dashboard + submission polish | ⏳ Next |

## Repository layout

```
backend/            FastAPI service + lifecycle worker
  app/core/         settings, structured logging, problem+json errors, request-id middleware
  app/db/           async SQLAlchemy engine/session, declarative base
  app/cache/        Redis client
  app/api/          health probes, /api/v1 router
  app/workers/      auction lifecycle worker (separate process)
  alembic/          migrations
  tests/
frontend/           React SPA
  src/app/          router, providers, theme, React Query client
  src/api/          typed fetch client (problem+json → ApiError, server-time sync)
  src/features/     feature folders: auth, rfqs (list, create/edit, details), system
docker-compose.yml  postgres, redis, mailpit, api, worker, frontend
```

## Running with Docker (recommended)

Requires Docker Desktop.

```bash
cp .env.example .env    # optional: change host ports if 5432/6379/8080/5173 are taken
make up                 # or: docker compose up -d --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 (the **System** page shows live Postgres/Redis status) |
| Mailpit (dev inbox) | http://localhost:8025 — every email the app sends lands here |
| API docs (Swagger) | http://localhost:8080/api/v1/docs |
| Liveness / readiness | http://localhost:8080/health/live · http://localhost:8080/health/ready |

The API container runs `alembic upgrade head` on start. `make logs`, `make ps`, `make down`.

### Demo accounts

```bash
make seed    # idempotent; refuses to run in staging/production
```

| Role | Email | Password |
|---|---|---|
| Buyer | buyer@example.com | Demo@12345 |
| Supplier | supplier1@example.com … supplier4@example.com | Demo@12345 |

In dev mode the login page has one-click buttons that fill these in. The seed also creates
three demo RFQs for the buyer (one live, one upcoming, one ended) with suppliers invited.

### Supplier onboarding (invite-only)

Public sign-up creates **buyer** accounts only. To bring in a supplier:

1. As the buyer, create an RFQ (or open one) and invite the supplier's email.
2. Open Mailpit (http://localhost:8025). An existing supplier gets a "New RFQ" notice; a new
   email gets a single-use sign-up link (valid 7 days, rotated if you press **Resend**).
3. Open the link and choose a name, company and password. The account is created as a
   supplier and attached to every RFQ that email was invited to.

## Production-style stack

```bash
cp .env.prod.example .env.prod      # set JWT_SECRET_KEY and POSTGRES_PASSWORD
make prod-up                        # → http://localhost:8088 (Mailpit: :8026)
make prod-down
```

- One origin: **Nginx** serves the built SPA and proxies `/api`, `/health` and the `/ws`
  WebSocket to the API. Postgres and Redis publish no ports.
- Runtime-only, non-root images (API image 345 MB vs 509 MB dev); migrations run as a one-shot
  `migrate` job before the API starts; 2 uvicorn workers (safe: WebSocket fan-out is via Redis).
- `ENVIRONMENT=production` enforces a strong `JWT_SECRET_KEY`, `Secure` cookies, hides the API
  docs, enables HSTS. Nginx adds a strict Content-Security-Policy, long-lived caching for
  fingerprinted assets, gzip, and a 1 MB body limit.
- Demo seed data is refused in production: register a buyer in the UI and invite suppliers
  (emails land in Mailpit).

## Running locally without Docker

```bash
make setup                                   # backend venv + frontend node_modules
docker compose up -d postgres redis          # or point backend/.env at your own instances
cp backend/.env.example backend/.env
cd backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload --port 8080
cd backend && .venv/bin/python -m app.workers.lifecycle   # separate terminal
cd frontend && npm run dev                                 # proxies /api, /health, /ws to :8080
```

## Quality checks

```bash
make check    # backend: ruff, mypy (strict), pytest · frontend: eslint, tsc, prettier, vitest, build
```

CI (`.github/workflows/ci.yml`) runs the same checks, applies migrations up/down/up against a
real Postgres, and builds the Docker images.

## Auction rules (design decisions)

The assignment leaves some behaviour open; these are the rules the engine implements
(`backend/app/domain/bidding.py`, covered by unit tests that include the spec's examples).

| # | Rule |
|---|---|
| D1 | A quote's price is **freight + origin + destination** charges (computed by Postgres). |
| D2 | A supplier may bid repeatedly; each new bid must be **strictly lower** than their current one. Their latest bid is their active quote. |
| D3 | Equal totals: the **earlier** bid ranks higher. |
| D4 | Extension: `new close = min(current close + Y, forced close)` — never past the forced close. |
| D5 | Trigger window is `[current close − X, current close)`; it **slides** with each extension. Bids are accepted in `[start, current close)`. |
| D6 | "Any rank change" = a supplier who **already had a rank** moved. A newcomer entering at the bottom isn't a change. |
| D7 | "L1 change" needs a previous L1 — the very first bid doesn't count. |
| D8 | **Force Closed** = the auction ended at the forced close (extensions hit the cap); **Closed** = it ended earlier. |
| D9 | "Now" is the **database clock**, read after taking the auction's row lock. |
| D10 | Visibility: the buyer sees everything. Suppliers see all prices and ranks, but competitors appear as "Bidder N" without their charge breakdown. |
| D11 | Schedule and auction rules can be edited only before bidding starts. |
| D12 | Suppliers are **invite-only**; public sign-up creates buyers. |
| D13 | An invite can be removed until the auction ends, **unless that supplier has bid** — then they stay. |
| D14 | A quote must stay valid **at least until the pickup date**, so the winning price can't lapse before the goods move. |

**Concurrency:** each bid runs in one transaction holding the RFQ's row lock (`SELECT … FOR
UPDATE`), so bids on one auction are serialised (others run in parallel); ranking before/after,
the extension and the activity-log entries commit atomically. A test fires 30 simultaneous bids
and checks the invariants (close ≤ forced close, one log entry per extension, correct L1,
strictly decreasing bids per supplier).

## Lifecycle worker

`python -m app.workers.lifecycle` (the `worker` service in Docker Compose) runs a 1-second tick:

- **SCHEDULED → ACTIVE** at bid start (log: *Bidding opened*).
- **ACTIVE → CLOSED** at the (possibly extended) close, or **FORCE_CLOSED** if extensions
  reached the forced close; records `closed_at`, the winning bid, bid/bidder/extension counts.
- Uses `SELECT … FOR UPDATE SKIP LOCKED`, so several replicas can run safely (tested with 4
  workers racing over 12 auctions: each closed exactly once). A row locked by an in-flight
  bid is skipped and re-checked on the next tick.
- Catches up after downtime (logs both the start and the close).
- Publishes a heartbeat to Redis; `/health/ready` and the **System** page show whether it's alive.

Readers never depend on the worker being on time: status is always derived from the clock,
and bids re-check the time under the row lock.

## Real-time updates

Pages showing live auctions hold **one WebSocket per browser tab** (`/ws`):

```
bid / worker ──commit──▶ Redis PUBLISH auction:{id} ──▶ every API process ──▶ subscribed sockets
```

- Auth is the first message (`{"type":"auth","token":…}`), never the URL; the socket closes
  with `4401` when the access token expires and the client refreshes and reconnects.
- Subscriptions are access-checked like `GET /rfqs/{id}`. Messages carry only public facts
  (status, close time, extension reason, current L1 price); clients then refetch their own
  leaderboard/activity view, so competitor anonymity is enforced in one place.
- Each message has a `seq` (latest activity-log id). After a reconnect the server sends a
  `SNAPSHOT`; if its `seq` moved on, the client refetches what it missed.
- Reconnects with backoff; while not live the UI falls back to polling (a "Live / Reconnecting…"
  indicator shows which). Extensions and closes pop a toast.

**Winner email:** when the worker closes an auction with bids, the L1 supplier gets
"You won RFQ-…" (price, pickup date, link). Sent after the close is committed.

**Known limitation (by design, for scope):** publishing and the winner email happen after the
commit, best-effort. If the process dies in that instant, the auction data is still correct but
that one notification is lost (clients recover on their next refresh). A transactional outbox
would make delivery guaranteed.

## Abuse protection

Redis fixed-window rate limits (atomic Lua script). They **fail open**: if Redis is down,
requests are allowed and a warning is logged.

| Endpoint | Limit | Key |
|---|---|---|
| `POST /auth/login` | 30/min · 10 per 5 min | client IP · account email |
| `POST /auth/register` | 10/hour | client IP |
| `POST /auth/invitations/inspect`, `/accept` | 20/min | client IP |
| `POST /auth/refresh` | 60/min | client IP |
| `POST /rfqs/{id}/bids` | 30/min | supplier + RFQ |
| Creating/sending invitations | 200/hour | buyer |

Over the limit → `429 RATE_LIMITED` with `Retry-After`.

## Load test

`make loadtest` (production stack, through Nginx): 60 suppliers × 3 live auctions × 6 bids, all
inside the trigger window (every bid takes the extension path), plus 20 WebSocket viewers. After
the run it re-checks the invariants in the database.

| Metric | Result |
|---|---|
| Bids accepted | 1,080 / 1,080 (0 errors) |
| Bid latency p50 / p95 / max | 32 ms / 1.07 s / 1.6 s |
| WebSocket push lag p50 / p95 | 9 ms / 68 ms |
| Invariants (close ≤ forced, 1 log entry per extension, stored L1 = true L1, every bid logged) | OK |

The p95 tail is the opening burst: all 60 suppliers bid on one auction within ~1 s, and bids on
a single auction are deliberately serialised (row lock) so extensions stay correct. Bids on
different auctions run in parallel.

What the first run found (p50 1.1 s, p95 8.1 s, two 502s), and the fixes:
- Requests waiting for an auction's row lock each held a pooled DB connection, starving bids
  on other auctions → same-auction bids now queue **in-process before** taking a connection, and
  the auth lookup uses its own short session.
- Fewer queries under the lock (one ranking query; `total_amount` returned by the INSERT).
- 502s were a keep-alive race (uvicorn closed idle connections after 5 s, Nginx reused them) →
  uvicorn keep-alive 75 s > Nginx 60 s.

## Authentication

- `POST /api/v1/auth/register | login` return a short-lived **access token** (15 min JWT, kept in
  memory by the SPA) and set a **refresh token** as an `httpOnly`, `SameSite=Strict` cookie
  scoped to `/api/v1/auth`.
- `POST /auth/refresh` rotates the refresh token on every use. Replaying an already-rotated
  token while the session is live is treated as theft: the whole session is revoked.
- Only a SHA-256 hash of each refresh token is stored. Passwords use Argon2id.
- The SPA refreshes ~1 min before expiry, retries a request once on `TOKEN_EXPIRED`, and
  serialises refreshes across browser tabs (Web Locks) so rotation never races.
- Roles: `BUYER`, `SUPPLIER` (self-service sign-up) and `ADMIN`. Endpoints use
  `BuyerUser` / `SupplierUser` / `require_roles(...)` dependencies.
- In staging/production the app refuses to start without a strong `JWT_SECRET_KEY` and
  `REFRESH_COOKIE_SECURE=true`.

## Conventions

- All timestamps are UTC `timestamptz`; money is `NUMERIC` / `Decimal`, never float.
- Errors are RFC 7807 `application/problem+json` with a stable `code` field the UI can switch on.
- Every response carries an `X-Request-ID`; logs are structured JSON (pretty in local dev).
- After adding frontend dependencies run `make fe-lock`, so `package-lock.json` matches the npm
  in the Docker image (otherwise `npm ci` fails in the image build).
- Backend tests include integration tests against a real `rfq_auction_test` database (created
  and migrated automatically). They skip if Postgres is down, except in CI.
