"""
Run all Autobiz end-to-end scenarios against the deployed Docker app.

Each scenario drives real HTTP calls to the backend, with LLM actors simulating
customers / vendors / logistics operators.  A judge LLM evaluates each
conversation trajectory at the end.

Usage:
    python tests/run_all.py
    python tests/run_all.py --base-url http://my-server:8000
    python tests/run_all.py --scenarios 1 2a 5c 6b
    python tests/run_all.py --model openai:gpt-4o

Prerequisites:
    1. Docker stack running:  cd app && docker compose up -d
    2. Backend healthy:       curl http://localhost:8000/health
    3. API key for TEST_MODEL in env:
          GOOGLE_API_KEY      for google-gla:gemini-2.0-flash  (default)
          OPENAI_API_KEY      for openai:gpt-4o
          ANTHROPIC_API_KEY   for anthropic:claude-3-5-sonnet-latest

Dependencies (install alongside app requirements):
    pip install httpx reportlab
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Auto-load app/.env so API keys are available without manual export
_env_file = Path(__file__).resolve().parents[1] / "app" / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.shared.actors import TEST_MODEL
from tests.shared.client import AutobizClient
from tests.shared.helpers import print_verdict

import tests.test_product_available      as s1
import tests.test_product_unavailable    as s2
import tests.test_payment_details        as s3_4
import tests.test_payment_verification   as s5
import tests.test_logistics              as s6

# Map scenario key → (label, async run function)
ALL_SCENARIOS = {
    "1":  ("Product Available — Donrey Fashion / Sneakers",             s1.run),
    "2a": ("Wrong Attribute — Kemi Surprises / Blue Shirt M",           s2.run_2a),
    "2b": ("Product Not Available — Manny Gadgets / Diamond Ring",      s2.run_2b),
    "3":  ("Bank Details from DB — Tesla Tech / Laptop",                s3_4.run_3),
    "4":  ("No Payment Link — Junae Cosmetics",                         s3_4.run_4),
    "5a": ("Inappropriate Receipt — Manny Gadgets / CV Upload",         s5.run_5a),
    "5b": ("Invalid Receipt — Kemi Surprises / Wrong Amount",           s5.run_5b),
    "5c": ("Valid Receipt — Tesla Tech / Laptop $1500",                 s5.run_5c),
    "6a": ("Logistics Agreed — Junae Cosmetics",                        s6.run_6a),
    "6b": ("Logistics Reschedule — Donrey Fashion",                     s6.run_6b),
    "6c": ("Vendor Receives Logistics Details — Manny Gadgets",         s6.run_6c),
}


async def main(base_url: str, model: str, scenarios: list[str]) -> None:
    # ── Health check ───────────────────────────────────────────────────────────
    client = AutobizClient(base_url)
    healthy = await client.health_check()
    if not healthy:
        print(f"\n✗  Backend at {base_url} is not reachable.")
        print("   Start the Docker stack:  cd app && docker compose up -d")
        sys.exit(1)

    print(f"\n{'═' * 70}")
    print(f"  Autobiz End-to-End Test Suite")
    print(f"{'═' * 70}")
    print(f"  Backend : {base_url}")
    print(f"  Model   : {model}")
    print(f"  Scenarios: {', '.join(scenarios)}")
    print(f"{'═' * 70}\n")

    results: dict[str, tuple[str, object, float]] = {}

    for key in scenarios:
        if key not in ALL_SCENARIOS:
            print(f"  ⚠  Unknown scenario '{key}', skipping.")
            continue

        label, run_fn = ALL_SCENARIOS[key]
        print(f"\n{'═' * 70}")
        print(f"  [{key}] {label}")
        print(f"{'═' * 70}")

        t_start = time.time()
        try:
            verdict = await run_fn(base_url, model)
            elapsed = time.time() - t_start
            results[key] = (label, verdict, elapsed)
        except Exception as exc:
            elapsed = time.time() - t_start
            # Build a synthetic failed verdict
            from tests.shared.actors import JudgeVerdict
            verdict = JudgeVerdict(
                passed=False,
                score=0.0,
                reason=f"EXCEPTION: {exc}",
                found_criteria=[],
                missing_criteria=["Scenario raised an unexpected exception — see traceback above"],
            )
            results[key] = (label, verdict, elapsed)
            import traceback
            traceback.print_exc()

    # ── Summary ────────────────────────────────────────────────────────────────
    passed_count = sum(1 for _, (_, v, _) in results.items() if v.passed)
    total        = len(results)

    print(f"\n\n{'#' * 70}")
    print(f"#  FINAL SUMMARY  —  {passed_count}/{total} passed")
    print(f"{'#' * 70}")

    for key, (label, v, elapsed) in results.items():
        ok    = v.passed
        icon  = "✓" if ok else "✗"
        color = "\033[92m" if ok else "\033[91m"
        reset = "\033[0m"
        print(
            f"  {color}{icon}{reset}  [{key:>2}]  {label:<52}  "
            f"score={v.score:.2f}  ({elapsed:.1f}s)"
        )

    if passed_count < total:
        print(f"\n{'─' * 70}")
        print("  Failed scenarios:")
        for key, (label, v, _) in results.items():
            if not v.passed:
                print(f"\n  [{key}] {label}")
                print(f"        {v.reason}")
                for m in v.missing_criteria:
                    print(f"        ✗ {m}")

    print(f"{'#' * 70}\n")
    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Autobiz end-to-end test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AUTOBIZ_BASE_URL", "http://localhost:8000"),
        help="Base URL of the deployed Docker app.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("TEST_MODEL", TEST_MODEL),
        help="LLM model for actor agents.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=list(ALL_SCENARIOS.keys()),
        choices=list(ALL_SCENARIOS.keys()),
        metavar="ID",
        help=(
            "Which scenarios to run. "
            f"Options: {', '.join(ALL_SCENARIOS.keys())}. "
            "Default: all."
        ),
    )
    args = parser.parse_args()
    os.environ["TEST_MODEL"] = args.model   # propagate to all actor modules

    asyncio.run(main(args.base_url, args.model, args.scenarios))
