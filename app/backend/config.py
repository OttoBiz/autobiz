"""
Configuration file for Ottobiz backend.
Contains all environment variables and settings.
"""
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

# Debug mode - when True, tier restrictions are disabled
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Model Configuration
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.0-flash")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")

# Database Configuration (Supabase/PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_USERNAME = os.getenv("DATABASE_USERNAME", "")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")
DATABASE_HOST = os.getenv("DATABASE_HOST", "")
DATABASE_PORT = os.getenv("DATABASE_PORT", "5432")
DATABASE_NAME = os.getenv("DATABASE_NAME", "")

# Redis Configuration
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_SERVER_HOST = os.getenv("REDIS_SERVER_HOST", "localhost")
REDIS_SERVER_PORT = int(os.getenv("REDIS_SERVER_PORT", "6379"))
REDIS_SERVER_PASSWORD = os.getenv("REDIS_SERVER_PASSWORD", "")

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Paystack Configuration (Optional)
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")

# WhatsApp Configuration
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# NOTE: WhatsApp Flow IDs and tenant Flow screen names are per-tenant; they
# live in the tenant-credentials store (planned), not in global config.

# Business Tier Plans
TIER_FREE = "free"
TIER_GOLD = "gold"
TIER_PLATINUM = "platinum"

# Cloudflare R2 / S3-compatible object storage (inbound media uploads).
# Set R2_PUBLIC_BASE_URL when the bucket is fronted by a public custom domain
# (e.g. https://media.example.com); otherwise the uploader falls back to a
# presigned URL valid for R2_PRESIGN_TTL seconds.
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.getenv("R2_BUCKET", "")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "")
R2_PRESIGN_TTL = int(os.getenv("R2_PRESIGN_TTL", "3600"))

# Logging
LOG_FILE = os.getenv("LOG_FILE", "app.log")

class Config:
    """Configuration class for easy access"""
    DEBUG = DEBUG
    MODEL_NAME = MODEL_NAME
    MODEL_API_KEY = MODEL_API_KEY
    DATABASE_URL = DATABASE_URL
    REDIS_URL = REDIS_URL
    SUPABASE_URL = SUPABASE_URL
    SUPABASE_KEY = SUPABASE_KEY
    PAYSTACK_PUBLIC_KEY = PAYSTACK_PUBLIC_KEY
    PAYSTACK_SECRET_KEY = PAYSTACK_SECRET_KEY
    WHATSAPP_API_KEY = WHATSAPP_API_KEY
    WHATSAPP_PHONE_NUMBER_ID = WHATSAPP_PHONE_NUMBER_ID

config = Config()

