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
| 3 | Bidding engine: bids, ranking, auto-extensions, activity log | ⏳ Next |
| 4–8 | Lifecycle worker, real-time, caching, hardening, analytics | Planned |

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
