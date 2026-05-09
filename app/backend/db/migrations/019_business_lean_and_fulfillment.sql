-- Migration 019: Lean down `businesses` + add fulfillment shape +
-- retire vendor/logistics tenant distinction.
--
-- Drops on businesses:
--   * product_schema  — stored as `{}` everywhere; the per-tenant attribute
--     spec was an idea that never got wired into the agent or product code,
--     and a stale schema vs. live products is a worse footgun than no schema.
--   * human_agent_phone / human_agent_email — escalation paths route through
--     the `contacts` address book now; these columns were declared on the
--     Pydantic model and projected by db_utils SELECTs but never read.
--   * business_type — `contacts.role` is the right home for the
--     vendor / logistics distinction: a tenant doesn't BE a logistics
--     provider, they HAVE logistics contacts. With the frontend retired
--     there's no remaining reader of this column.
--
-- Drops on orders:
--   * logistic_id (FK → businesses) — followed business_type out the door.
--     Logistics for an order is a contact relationship now, not a tenant
--     pointer; if/when an order needs to remember which courier it shipped
--     with, that lives as a `contact_id` reference under the orders table
--     or on a future `shipments` row, not as a businesses(id) FK.
--
-- Adds on businesses:
--   * fulfillment_modes TEXT[] — `{delivery}`, `{pickup}`, or both. Array
--     instead of an enum so "both" is a multi-membership rather than a
--     fake third value; CHECK constraints keep it bounded.
--   * physical_address / physical_city / physical_state — required at the
--     application layer when 'pickup' ∈ fulfillment_modes (a tenant can be
--     created before the operator fills these in, so the SQL stays loose).

DROP INDEX IF EXISTS idx_orders_logistic;
ALTER TABLE orders DROP COLUMN IF EXISTS logistic_id;

DROP INDEX IF EXISTS idx_businesses_type;
ALTER TABLE businesses DROP COLUMN IF EXISTS business_type;
ALTER TABLE businesses DROP COLUMN IF EXISTS product_schema;
ALTER TABLE businesses DROP COLUMN IF EXISTS human_agent_phone;
ALTER TABLE businesses DROP COLUMN IF EXISTS human_agent_email;

ALTER TABLE businesses
    ADD COLUMN IF NOT EXISTS fulfillment_modes TEXT[] NOT NULL DEFAULT ARRAY['delivery'],
    ADD COLUMN IF NOT EXISTS physical_address TEXT,
    ADD COLUMN IF NOT EXISTS physical_city TEXT,
    ADD COLUMN IF NOT EXISTS physical_state TEXT;

ALTER TABLE businesses
    ADD CONSTRAINT businesses_fulfillment_modes_bounded
    CHECK (
        fulfillment_modes <@ ARRAY['delivery', 'pickup']
        AND cardinality(fulfillment_modes) >= 1
    );
