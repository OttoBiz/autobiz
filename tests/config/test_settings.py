"""Functional tests for config/settings.py"""

import pytest
from pydantic import ValidationError
from config.settings import Settings


@pytest.fixture
def clean_env(monkeypatch):
    """Fixture to provide clean environment without .env file loading."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)
    monkeypatch.delenv("API_HOST", raising=False)
    monkeypatch.delenv("API_PORT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    return monkeypatch


def test_settings_with_required_fields(clean_env):
    """Test that Settings can be created with required fields."""
    settings = Settings(_env_file=None, database_url="postgresql://user:pass@localhost:5432/test")
    assert settings.database_url == "postgresql://user:pass@localhost:5432/test"


def test_settings_with_defaults(clean_env):
    """Test that Settings uses default values for optional fields."""
    settings = Settings(_env_file=None, database_url="postgresql://user:pass@localhost:5432/test")

    assert settings.db_pool_min_size == 10
    assert settings.db_pool_max_size == 20
    assert settings.db_pool_max_queries == 50000
    assert settings.db_pool_max_inactive_connection_lifetime == 300.0
    assert settings.db_command_timeout == 60.0
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 8000
    assert settings.environment == "development"


@pytest.mark.parametrize(
    "config,expected",
    [
        (
            {
                "db_pool_min_size": 5,
                "db_pool_max_size": 15,
                "environment": "production",
            },
            {"db_pool_min_size": 5, "db_pool_max_size": 15, "environment": "production"},
        ),
        (
            {"db_command_timeout": 30.0, "api_port": 3000},
            {"db_command_timeout": 30.0, "api_port": 3000},
        ),
        (
            {"api_host": "127.0.0.1", "db_pool_max_queries": 10000},
            {"api_host": "127.0.0.1", "db_pool_max_queries": 10000},
        ),
    ],
)
def test_settings_with_custom_values(clean_env, config, expected):
    """Test that Settings accepts custom values for optional fields."""
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost:5432/test",
        **config,
    )

    for key, value in expected.items():
        assert getattr(settings, key) == value


def test_settings_missing_required_field(clean_env):
    """Test that Settings raises ValidationError when required field is missing."""
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_settings_ignores_extra_fields(clean_env):
    """Test that Settings ignores extra fields from environment."""
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@localhost:5432/test",
        extra_field="should_be_ignored",
    )

    assert settings.database_url == "postgresql://user:pass@localhost:5432/test"
    assert not hasattr(settings, "extra_field")


def test_settings_from_environment(clean_env):
    """Test that Settings loads values from environment variables."""
    clean_env.setenv("DATABASE_URL", "postgresql://envuser:envpass@envhost:5432/envdb")
    clean_env.setenv("DB_POOL_MIN_SIZE", "20")
    clean_env.setenv("API_PORT", "9000")
    clean_env.setenv("ENVIRONMENT", "staging")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql://envuser:envpass@envhost:5432/envdb"
    assert settings.db_pool_min_size == 20
    assert settings.api_port == 9000
    assert settings.environment == "staging"


def test_settings_case_insensitive(clean_env):
    """Test that Settings is case insensitive for environment variables."""
    clean_env.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    clean_env.setenv("db_pool_min_size", "5")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql://user:pass@localhost:5432/test"
    assert settings.db_pool_min_size == 5


def test_settings_env_overrides_defaults(clean_env):
    """Test that environment variables override default values."""
    clean_env.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    clean_env.setenv("DB_POOL_MIN_SIZE", "50")

    settings = Settings(_env_file=None)

    assert settings.db_pool_min_size == 50  # Overridden
    assert settings.db_pool_max_size == 20  # Default


@pytest.mark.parametrize(
    "invalid_value,field",
    [
        ("not_a_number", "db_pool_min_size"),
        ("invalid", "api_port"),
        ("not_a_float", "db_command_timeout"),
    ],
)
def test_settings_validation_errors(clean_env, invalid_value, field):
    """Test that Settings validates field types correctly."""
    clean_env.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
    clean_env.setenv(field.upper(), invalid_value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
