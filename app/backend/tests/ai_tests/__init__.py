"""
AI-driven end-to-end tests against a running Autobiz API (e.g. Docker Compose on port 8000).

Run from the `app` directory (PYTHONPATH includes backend):

    pytest backend/tests/ai_tests -v -m ai_e2e

Environment:
    AUTOBIZ_BASE_URL   — default http://127.0.0.1:8000
    MODEL_API_KEY      — required for actor + judge LLMs (same provider as backend)
    MODEL_NAME         — optional override

Narrow runs:
    pytest backend/tests/ai_tests -k "fresh and product_available"
    pytest backend/tests/ai_tests -k "receipt_"   # six receipt scenarios (structured + plaintext PDF + corrupt)
"""
