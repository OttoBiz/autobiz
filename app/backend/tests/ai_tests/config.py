import os

from dotenv import load_dotenv

load_dotenv()

AUTOBIZ_BASE_URL = os.getenv("AUTOBIZ_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT_S = float(os.getenv("AI_TEST_TIMEOUT_S", "120"))
INBOX_POLL_INTERVAL_S = float(os.getenv("AI_TEST_INBOX_POLL_S", "2"))
INBOX_POLL_MAX_S = float(os.getenv("AI_TEST_INBOX_MAX_WAIT_S", "90"))
