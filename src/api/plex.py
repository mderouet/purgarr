import time

import requests
from typing import Any

from ..config import PLEX_URL, PLEX_TOKEN
from ..utils.logger import setup_logger

logger = setup_logger()


class PlexClient:
    """Client for interacting with the Plex API."""

    def __init__(self, base_url: str = PLEX_URL, token: str = PLEX_TOKEN):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.token = token
        self.enabled = bool(self.base_url and self.token)
        if not self.enabled:
            logger.info("Plex integration disabled (no URL or token configured).")

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any | None:
        if not self.enabled:
            return None
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        params["X-Plex-Token"] = self.token
        try:
            response = requests.get(
                url,
                params=params,
                headers={"Accept": "application/json"},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Plex GET {endpoint} failed: {e}")
            return None

    def _get_no_body(self, endpoint: str) -> bool:
        """Send a GET request that returns no JSON body (e.g. refresh, scan)."""
        if not self.enabled:
            return False
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.get(
                url,
                params={"X-Plex-Token": self.token},
                timeout=30,
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Plex GET {endpoint} failed: {e}")
            return False

    def _put(self, endpoint: str) -> bool:
        if not self.enabled:
            return False
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.put(
                url,
                params={"X-Plex-Token": self.token},
                timeout=30,
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Plex PUT {endpoint} failed: {e}")
            return False

    def get_library_sections(self) -> list[dict[str, Any]]:
        """Get all Plex library sections."""
        if not self.enabled:
            return []
        data = self._get("/library/sections")
        if data and "MediaContainer" in data:
            return data["MediaContainer"].get("Directory", [])
        return []

    def get_all_items_with_play_data(self) -> list[dict[str, Any]]:
        """Fetch all movies and shows from Plex with play data.

        Returns a flat list of Plex metadata dicts containing lastViewedAt
        (epoch seconds), viewCount, and Guid array for provider ID matching.
        """
        if not self.enabled:
            return []

        sections = self.get_library_sections()
        media_sections = [
            s for s in sections if s.get("type") in ("movie", "show")
        ]

        items = []
        for section in media_sections:
            section_id = section["key"]
            data = self._get(
                f"/library/sections/{section_id}/all",
                params={"includeGuids": 1},
            )
            if data and "MediaContainer" in data:
                metadata = data["MediaContainer"].get("Metadata", [])
                items.extend(metadata)

        logger.debug(f"Found {len(items)} items in Plex with play data.")
        return items

    @staticmethod
    def extract_imdb_id(plex_item: dict[str, Any]) -> str | None:
        """Extract IMDb ID from a Plex item's Guid array.

        Plex returns guids like: [{"id": "imdb://tt1234567"}, {"id": "tmdb://123"}]
        """
        guids = plex_item.get("Guid", [])
        for guid in guids:
            guid_str = guid.get("id", "")
            if guid_str.startswith("imdb://"):
                return guid_str[7:]
        return None

    def get_show_seasons(self, show_rating_key: str) -> list[dict[str, Any]]:
        """Fetch all seasons for a show with watch progress.

        Returns season dicts with index (season number), viewedLeafCount,
        leafCount, and lastViewedAt.
        """
        if not self.enabled:
            return []
        data = self._get(f"/library/metadata/{show_rating_key}/children")
        if data and "MediaContainer" in data:
            return data["MediaContainer"].get("Metadata", [])
        return []

    def refresh_and_clean(self) -> None:
        """Refresh all library sections and empty trash."""
        if not self.enabled:
            return

        sections = self.get_library_sections()
        media_sections = [
            s for s in sections if s.get("type") in ("movie", "show")
        ]

        if not media_sections:
            logger.warning("No movie/show library sections found in Plex.")
            return

        for section in media_sections:
            section_id = section["key"]
            section_title = section.get("title", section_id)
            logger.debug(f"Refreshing Plex library section: {section_title}")
            self._get_no_body(f"/library/sections/{section_id}/refresh")

        # Wait for Plex to detect missing files
        logger.debug("Waiting 10s for Plex to process library scan...")
        time.sleep(10)

        for section in media_sections:
            section_id = section["key"]
            section_title = section.get("title", section_id)
            logger.debug(f"Emptying Plex trash for section: {section_title}")
            self._put(f"/library/sections/{section_id}/emptyTrash")
