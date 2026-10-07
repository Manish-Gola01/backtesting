"""Settings: sane defaults and process-wide caching."""
from app.core.config import get_settings


def test_settings_defaults():
    settings = get_settings()
    assert settings.API_V1_PREFIX == "/api/v1"
    assert settings.APP_ENV == "development"
    assert settings.MAX_UPLOAD_MB > 0
    assert settings.CORS_ORIGINS  # non-empty allow-list


def test_settings_is_cached_singleton():
    assert get_settings() is get_settings()
