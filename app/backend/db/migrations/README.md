# Database Migrations

This directory contains SQL migration files for the autobiz database schema.

## Migration File Naming Convention

Migrations follow the pattern: `<version>_<name>.sql`

- `version`: 3-digit zero-padded integer (e.g., 001, 002, 003)
- `name`: Descriptive snake_case name (e.g., initial_schema, add_user_roles)

Examples:
- `001_initial_schema.sql`
- `002_add_product_variants.sql`
- `003_add_user_authentication.sql`

## Creating a New Migration

1. Create a new file with the next version number:
   ```bash
   touch services/db/migrations/002_add_product_variants.sql
   ```

2. Write your SQL DDL statements:
   ```sql
   -- Add product variants table
   CREATE TABLE product_variants (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       product_id UUID REFERENCES products(id) ON DELETE CASCADE,
       name TEXT NOT NULL,
       price_modifier DECIMAL(10, 2) DEFAULT 0,
       attributes JSONB NOT NULL DEFAULT '{}'
   );
   ```

3. Run the migration:
   ```bash
   uv run services/db/migrate.py
   ```

## Rollback Support (Optional)

To support rollback, create a corresponding `_down.sql` file:

- UP migration: `002_add_product_variants.sql`
- DOWN migration: `002_add_product_variants_down.sql`

Example down migration:
```sql
DROP TABLE IF EXISTS product_variants;
```

Rollback usage:
```bash
uv run services/db/migrate.py --rollback 1
```

## Running Migrations

```bash
# Run all pending migrations
uv run services/db/migrate.py

# Check migration status
uv run services/db/migrate.py --status

# Rollback to specific version
uv run services/db/migrate.py --rollback <version>
```

## Migration Tracking

All applied migrations are tracked in the `schema_migrations` table:

```sql
SELECT * FROM schema_migrations ORDER BY version;
```

## Best Practices

1. **One migration per logical change** - Don't bundle unrelated changes
2. **Never edit applied migrations** - Create a new migration to modify schema
3. **Test locally first** - Always test migrations on a local database
4. **Idempotent when possible** - Use `IF NOT EXISTS`, `IF EXISTS` where appropriate
5. **Add indexes** - Don't forget indexes for foreign keys and frequently queried columns
6. **Include rollback** - For production, always include down migrations
