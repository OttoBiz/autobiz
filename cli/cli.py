"""Smoke-harness entry point.

Usage (interactive 4-tab TUI):

    .venv/bin/python -m cli.cli

Usage (headless scripted scenario, for CI):

    .venv/bin/python -m cli.cli --scenario vendor_confirmation

Required services:
    Redis     — `docker compose up redis` from app/
    Postgres  — `docker compose up postgres` from app/
    Model     — set MODEL_NAME and the matching provider API key (e.g.
                OPENAI_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY) before
                starting. Pass --model to override MODEL_NAME for one run.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# The backend package lives under app/; cli/ lives at the repo root.
_APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_APP_DIR / ".env")


# Provider env var → human label, in the order pydantic_ai checks. The smoke
# CLI doesn't try to pick the model for the user; it only verifies *some*
# provider key is set so the first agent.run doesn't crash with a confusing
# auth error mid-conversation.
_PROVIDER_KEYS = (
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
    ("GEMINI_API_KEY", "Gemini"),
    ("GOOGLE_API_KEY", "Google (Gemini)"),
    ("GROQ_API_KEY", "Groq"),
    ("MISTRAL_API_KEY", "Mistral"),
)


def _check_provider_key() -> tuple[str, str] | None:
    for var, label in _PROVIDER_KEYS:
        if os.getenv(var):
            return var, label
    return None


async def _run_migrations_if_needed() -> None:
    """Apply pending SQL migrations using the project's MigrationRunner."""
    from backend.db.migrate import MigrationRunner

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set; cannot run migrations.")
    runner = MigrationRunner(dsn)
    await runner.connect()
    try:
        await runner.run_migrations()
    finally:
        await runner.close()


def _print_setup_help(model_name: str) -> None:
    print("✗ No model provider API key found in environment.")
    print()
    print(f"  MODEL_NAME = {model_name!r}")
    print()
    print("  Set one of:")
    for var, label in _PROVIDER_KEYS:
        print(f"    {var:<24} ({label})")
    print()
    print("  Either export it in your shell or add it to app/.env, then re-run.")


async def _async_main(args: argparse.Namespace) -> int:
    # Late import: bringing in `backend.*` triggers Redis client construction
    # on first import, so make sure DEBUG and Redis env are set before we
    # touch the chatbot package.
    os.environ.setdefault("DEBUG", "true")

    if args.model:
        os.environ["MODEL_NAME"] = args.model

    from backend.config import MODEL_NAME

    provider = _check_provider_key()
    if provider is None:
        _print_setup_help(MODEL_NAME)
        return 2

    print(f"✓ Model: {MODEL_NAME}  (auth: {provider[1]})")

    from backend.db.connection import close_db, init_db

    try:
        await init_db()
    except Exception as exc:
        print(f"✗ Could not connect to Postgres: {exc}")
        print("  Start it with `docker compose up postgres` from app/.")
        return 3
    print("✓ Postgres pool ready")

    # Apply pending migrations so `businesses`, `users`, etc. exist before
    # the seed step tries to insert into them. No-op if already applied.
    try:
        await _run_migrations_if_needed()
    except Exception as exc:
        print(f"✗ Migration run failed: {exc}")
        return 4
    print("✓ Schema migrations up to date")

    from cli.seed import ensure_smoke_data, reset_smoke_state

    # Wipe per-customer state from prior sessions (chat history, outbound
    # tasks, channel identities, cursors, locks) so every CLI launch feels
    # like a clean start. Use --keep-state to skip when debugging.
    if not args.keep_state:
        try:
            await reset_smoke_state(args.business_id, args.customer_id)
        except Exception as exc:
            print(f"✗ Could not clear prior smoke state: {exc}")
            return 5
        print(
            f"✓ Cleared prior state for business={args.business_id[:8]} "
            f"customer={args.customer_id[:8]}"
        )

    try:
        await ensure_smoke_data(args.business_id, args.customer_id)
    except Exception as exc:
        print(f"✗ Could not seed business/customer rows: {exc}")
        return 5
    print(f"✓ Seeded business={args.business_id[:8]} customer={args.customer_id[:8]}")

    # Register the in-process channel + identity resolver before the
    # orchestrator runs its first turn.
    from backend.chatbot.channels.console import install as install_console

    install_console()
    print("✓ ConsoleChannel registered")

    try:
        if args.scenario:
            from cli import scenarios

            return await scenarios.run(args.scenario)

        # Interactive TUI mode. Imported lazily so the headless scenario
        # path doesn't pull in textual.
        from cli.tui import SmokeApp

        app = SmokeApp(
            business_id=args.business_id,
            customer_id=args.customer_id,
        )
        await app.run_async()
        return 0
    finally:
        await close_db()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cli.cli",
        description="Smoke harness — drive the agent stack as customer and vendor.",
    )
    parser.add_argument(
        "--model",
        help="Override MODEL_NAME for this run (e.g. 'openai:gpt-4o').",
    )
    parser.add_argument(
        "--business-id",
        dest="business_id",
        default="11111111-1111-1111-1111-111111111111",
        help="UUID for the test business (default: deterministic test value).",
    )
    parser.add_argument(
        "--customer-id",
        dest="customer_id",
        default="22222222-2222-2222-2222-222222222222",
        help="UUID for the test customer (default: deterministic test value).",
    )
    parser.add_argument(
        "--scenario",
        help="Run a scripted scenario instead of the interactive TUI.",
    )
    parser.add_argument(
        "--keep-state",
        dest="keep_state",
        action="store_true",
        help=(
            "Don't wipe prior per-customer state at startup. By default the "
            "CLI clears chat history, outbound tasks, channel identities, "
            "and cursors for the smoke customer so every launch feels fresh."
        ),
    )
    args = parser.parse_args()

    try:
        return asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        print("\n✓ Smoke harness stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
