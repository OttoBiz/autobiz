.PHONY: db-setup db-reset

# Apply all database schemas
db-setup:
	uv run python db/schema/run_migrations.py

# Drop all tables (use with caution!)
db-reset:
	@echo "WARNING: This will drop all tables!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		uv run python -c "import asyncio; import asyncpg; from config.settings import settings; asyncio.run((lambda: asyncpg.connect(settings.database_url))()).result().execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;'))"; \
		echo "✓ Database reset complete. Run 'make db-setup' to recreate tables."; \
	fi
