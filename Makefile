.PHONY: db-setup db-reset seed-db

# Apply all database schemas
db-setup:
	uv run python db/schema/run_migrations.py

# Seed database with test data for agent testing
seed-db:
	@echo "🌱 Seeding database with test data..."
	uv run python scripts/seed_test_data.py

# Drop all tables (use with caution!)
db-reset:
	@echo "WARNING: This will drop all tables!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		uv run python -c "import asyncio, asyncpg; from config.settings import settings; exec('async def f(): c=await asyncpg.connect(settings.database_url); await c.execute(\"DROP SCHEMA public CASCADE; CREATE SCHEMA public;\"); await c.close()'); asyncio.run(f())"; \
		echo "✓ Database reset complete. Run 'make db-setup' to recreate tables."; \
	fi
