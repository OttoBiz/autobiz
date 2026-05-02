-- Migration 013: Inventory dashboard fields (renumbered from spec's 012; 012 is product floor_price).

ALTER TABLE products
  ADD COLUMN reorder_point integer NOT NULL DEFAULT 0,
  ADD COLUMN image_url text;

CREATE TABLE stock_movements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id uuid NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES businesses(id),
  delta integer NOT NULL,
  reason text NOT NULL CHECK (reason IN ('restock','manual_set','correction','damage','sale','agent_decrement')),
  note text,
  actor_type text NOT NULL CHECK (actor_type IN ('operator','agent','system')),
  actor_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON stock_movements (product_id, created_at DESC);
CREATE INDEX ON stock_movements (business_id, created_at DESC);

-- Bulk import jobs backing POST /products/bulk-import + GET /products/bulk-import/{job_id}.
-- Jobs are retained ~30 days; GC is deferred to a separate sweeper (no TTL column here).
CREATE TABLE bulk_import_jobs (
  id text PRIMARY KEY,
  business_id uuid NOT NULL REFERENCES businesses(id),
  status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed')),
  total_rows int NOT NULL DEFAULT 0,
  processed int NOT NULL DEFAULT 0,
  created int NOT NULL DEFAULT 0,
  updated int NOT NULL DEFAULT 0,
  errors jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON bulk_import_jobs (business_id, created_at DESC);
