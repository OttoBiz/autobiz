"""Dump the products dashboard OpenAPI spec to a committed JSON file.

Why a standalone minimal app instead of importing ``app.main``: ``main.py``
calls ``setup_observability()`` and initialises database/redis clients at
import time. We don't want any of that firing during a doc dump (it
would require live env, network, secrets). Instead we build a tiny
FastAPI app here that mounts only the routers the dashboard frontend
codegens schemas from.

Run from the repo root::

    cd app && PYTHONPATH=. python backend/api/scripts/dump_openapi.py

The output path is computed from this file's location so the script is
reproducible from any cwd.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from fastapi import FastAPI


def _install_stubs() -> None:
    """Stub modules whose import fires real network/Redis side effects.

    ``backend.db.cache_utils`` instantiates a RedisCluster client at
    import time, which requires a reachable cluster. For an OpenAPI dump
    we never call the publishers -- only the schema metadata matters --
    so we replace the module with a no-op stub before the routers import
    it.
    """
    if "backend.db.cache_utils" in sys.modules:
        return
    stub = types.ModuleType("backend.db.cache_utils")

    class _NoopRedis:
        class _Client:
            def publish(self, *a, **kw):  # pragma: no cover - dump-only
                return 0

        _client = _Client()

        def get(self, *a, **kw):  # pragma: no cover - dump-only
            return None

        def set(self, *a, **kw):  # pragma: no cover - dump-only
            return None

    stub.redis_conn = _NoopRedis()

    async def _noop(*a, **kw):  # pragma: no cover - dump-only
        return None

    stub.get_user_state = _noop
    stub.set_user_state = _noop
    sys.modules["backend.db.cache_utils"] = stub


_install_stubs()


# Resolved relative to this file: app/backend/api/openapi.json
OUTPUT_PATH = (Path(__file__).resolve().parent.parent / "openapi.json").resolve()


def build_app() -> FastAPI:
    """Build a minimal FastAPI app exposing the dashboard routers.

    If an optional router fails to import (missing dep like logfire or a
    redis client that isn't installed in the dump environment), we fall
    back to the products router only and note the omission. The frontend
    primarily needs products schemas; the rest are best-effort.
    """
    app = FastAPI(title="Ottobiz API", version="1.0.0")

    # Products is the load-bearing router for codegen. Import it
    # unconditionally -- if this fails the dump should fail loudly.
    from backend.api.routers import products

    routers = [products]

    # Best-effort include for adjacent dashboard routers. If any of these
    # pull in deps we don't have at dump time, skip them rather than
    # crashing the products dump.
    for name in ("inventory", "analytics", "supply_chain"):
        try:
            module = __import__(
                f"backend.api.routers.{name}", fromlist=["router"]
            )
            routers.append(module)
        except Exception as exc:  # pragma: no cover - dump-time fallback
            print(f"[dump_openapi] skipping router '{name}': {exc}")

    for r in routers:
        app.include_router(r.router, prefix="/api/v1")

    return app


def dump(output_path: Path = OUTPUT_PATH) -> Path:
    app = build_app()
    spec = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(spec, indent=2, sort_keys=True))
    path_count = len(spec.get("paths", {}))
    print(f"[dump_openapi] wrote {output_path} ({path_count} paths)")
    return output_path


if __name__ == "__main__":
    dump()
