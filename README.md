# Autobiz

AI-powered customer service platform where businesses get dedicated agents to handle customer interactions, orders, payments, and shipping.

## Setup

**Install dependencies:**
```bash
uv sync
```

**Setup database:**
```bash
make db-setup
```

**Run development server:**
```bash
uv run uvicorn api.main:app --reload
```

## Database

**Apply schemas:**
```bash
make db-setup  # Safe to run multiple times
```

**Reset database:**
```bash
make db-reset  # Drops all tables (prompts for confirmation)
```

**Making schema changes:**
1. Create new numbered SQL file in `db/schema/`
2. Add tracking logic (see existing files for pattern)
3. Add to `Makefile` under `db-setup`
4. Run `make db-setup`

## Testing

```bash
uv run pytest
```
