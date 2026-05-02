# Products API — Deferred Work

Tracked items left after the initial 11-endpoint landing (commits `02ba874`..`ac96727` on `march-refactor`).

## Behavior gaps

- **Cross-tenant access returns 404, not 403.** Spec asked for 403 to avoid leaking existence, but the repo helpers return `None` for both "missing" and "wrong tenant", so distinguishing requires an extra query. Inline TODO in `routers/products.py`.
- **PATCH response is polymorphic.** When discontinuing a product with open orders the response shape becomes `{"product": ProductRead, "warnings": [...]}` instead of bare `ProductRead`. The committed `openapi.json` advertises `ProductRead` only, so the TanStack codegen will be wrong for that branch. Decide: drop the wrapper (surface warnings via response header), or model the union and regenerate.
- **Category allowlist not enforced.** `POST /products` and `POST /products/bulk-update` accept any category string. Spec says they must match `GET /products/categories`. v1 punted because the categories list is operator-defined and runtime-dynamic; revisit when the dashboard ships category management.

## Bulk paths

- **Bulk-import is inline, not async.** `POST /products/bulk-import` processes the CSV synchronously inside the request and returns the final job state. The `job_id` contract is preserved so the dashboard can poll `/bulk-import/{job_id}` without changing, but for files near the 10k limit the request will time out. Move to a background worker (the existing sweeper or a new task runner) before this is exposed to operators.
- **Bulk-import bypasses repo helpers.** It calls `get_db()` directly inside the loop instead of going through `create_product` / `patch_product`. Makes future unit tests painful and means the per-row stock-movement audit isn't guaranteed to follow the same code path as single-row writes. Refactor to call the helpers row-by-row.
- **Bulk-import / bulk-update don't emit pub/sub events.** Per-row publishes on a 10k-row import would be expensive; v1 leans on the agent cache TTL for invalidation. If the agent ever caches stock for longer than ~minutes, this becomes a correctness issue — emit a single summary event per affected business after a bulk run.

## Job lifecycle

- **`bulk_import_jobs` rows accumulate forever.** Migration 013 says they should live ~30 days then be GC'd; no sweeper exists yet. Add a periodic delete to the existing sweeper (or to `populate_db_on_startup`).

## Auth + deploy

- **Env vars not set in any deployed environment yet.** `BETTER_AUTH_JWKS_URL` and `BETTER_AUTH_ISSUER` must be added to the Python deploy config (Dokploy / docker-compose) before the dashboard can hit these endpoints.
- **No real auth integration test.** The smoke test overrides `require_session` with a fake. We have no end-to-end test that better-auth's actual JWKS round-trips through PyJWT correctly — first time we'll find out is in staging. Worth a one-off test against a local better-auth instance.

## Schema sync

- **`db/models.py:Product` does not include `reorder_point`, `image_url`, or `last_restocked_at` (derived).** That model is the agent-side Pydantic schema and isn't used by the new HTTP API, but if anything reads from it post-migration it will silently miss columns. Add the new fields when next touching that file.

## Frontend handoff (Plan 07 — not our work)

The dashboard team owns:
1. Replace `apps/web/src/data/mock-inventory.ts` with TanStack server functions in `apps/web/src/server/products.ts`.
2. Codegen Zod schemas from `app/backend/api/openapi.json`.
3. Wire row actions in `inventory-actions-dropdown.tsx`.
4. Stock-movements section in the detail drawer fed by `/stock-movements`.
