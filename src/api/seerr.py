import requests

from ..config import SEERR_URL, SEERR_API_KEY
from ..utils.logger import setup_logger

logger = setup_logger()


class SeerrClient:
    """Client for interacting with the Seerr API."""

    def __init__(self, base_url: str = SEERR_URL, api_key: str = SEERR_API_KEY):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.enabled = bool(self.base_url and self.api_key)
        if not self.enabled:
            logger.info("Seerr integration disabled (no URL or API key configured).")

    def trigger_availability_sync(self) -> bool:
        """Trigger the availability-sync job to update media statuses."""
        if not self.enabled:
            return False
        url = f"{self.base_url}/api/v1/settings/jobs/availability-sync/run"
        try:
            response = requests.post(
                url,
                headers={"X-Api-Key": self.api_key},
                timeout=30,
            )
            response.raise_for_status()
            logger.debug("Seerr availability sync triggered.")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Seerr availability sync failed: {e}")
            return False
