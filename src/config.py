import os

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Custom exception for missing configuration."""

    pass


def get_env(var_name: str, default: str | None = None) -> str:
    """Get an environment variable or return a default value."""
    value = os.getenv(var_name)
    if value is None:
        if default is not None:
            return default
        raise ConfigError(
            f"Required environment variable '{var_name}' not found. "
            "Please set it in your .env file."
        )
    return value


def get_env_bool(var_name: str, default: str = "false") -> bool:
    """Get an environment variable as a boolean."""
    return get_env(var_name, default).lower() in ("true", "1", "yes")


def get_env_int(var_name: str, default: str | None = None) -> int:
    """Get an environment variable as an integer."""
    return int(get_env(var_name, default))


def get_env_float(var_name: str, default: str | None = None) -> float:
    """Get an environment variable as a float."""
    return float(get_env(var_name, default))


# --- API connections ---
RADARR_URL = get_env("RADARR_URL")
RADARR_API_KEY = get_env("RADARR_API_KEY")

SONARR_URL = get_env("SONARR_URL")
SONARR_API_KEY = get_env("SONARR_API_KEY")

JELLYFIN_URL = get_env("JELLYFIN_URL")
JELLYFIN_API_KEY = get_env("JELLYFIN_API_KEY")

PLEX_URL = get_env("PLEX_URL", "")
PLEX_TOKEN = get_env("PLEX_TOKEN", "")

QBITTORRENT_URL = get_env("QBITTORRENT_URL", "")
QBITTORRENT_USERNAME = get_env("QBITTORRENT_USERNAME", "")
QBITTORRENT_PASSWORD = get_env("QBITTORRENT_PASSWORD", "")

# --- Media path ---
MEDIA_PATH = get_env("MEDIA_PATH")

# --- Space mode (reactive) ---
SPACE_MODE = get_env_bool("SPACE_MODE", "true")
FREE_SPACE_THRESHOLD_GB = get_env_float("FREE_SPACE_THRESHOLD_GB", "10")

# --- Age mode (proactive) ---
AGE_MODE = get_env_bool("AGE_MODE", "false")
MAX_AGE_DAYS = get_env_int("MAX_AGE_DAYS", "180")

# --- General ---
DRY_RUN = get_env_bool("DRY_RUN", "true")
VERBOSE = get_env_bool("VERBOSE", "false")
CRON_SCHEDULE = get_env("CRON_SCHEDULE", "")
