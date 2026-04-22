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

# WhatsApp Flow IDs. Each registered Flow on the WABA has a unique ID; the
# `request_info` helper below targets a generic "request information" flow
# that the business publishes once and reuses across agents.
FLOW_REQUEST_INFO_ID = os.getenv("FLOW_REQUEST_INFO_ID", "")

# Business Tier Plans
TIER_FREE = "free"
TIER_GOLD = "gold"
TIER_PLATINUM = "platinum"

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
    FLOW_REQUEST_INFO_ID = FLOW_REQUEST_INFO_ID

config = Config()

