import requests
from typing import Any

from ..config import JELLYFIN_URL, JELLYFIN_API_KEY
from ..utils.logger import setup_logger

logger = setup_logger()


class JellyfinClient:
    """Client for interacting with the Jellyfin API."""

    def __init__(
        self, base_url: str = JELLYFIN_URL, api_key: str = JELLYFIN_API_KEY
    ):
        if not base_url or not api_key:
            raise ValueError("Jellyfin URL and API key must be provided.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "X-Emby-Token": api_key,
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any | None:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Jellyfin GET {endpoint} failed: {e}")
            return None

    def _post(self, endpoint: str, params: dict[str, Any] | None = None) -> bool:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.post(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Jellyfin POST {endpoint} failed: {e}")
            return False

    def _delete(self, endpoint: str) -> bool:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.delete(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Jellyfin DELETE {endpoint} failed: {e}")
            return False

    def get_all_items_with_play_data(self) -> list[dict[str, Any]]:
        """Fetch all movies and series with PlayCount and LastPlayedDate.

        Uses the Items endpoint with admin-level API key (no userId needed).
        """
        items = []
        for item_type in ("Movie", "Series"):
            data = self._get(
                "/Items",
                params={
                    "IncludeItemTypes": item_type,
                    "Recursive": "true",
                    "Fields": "ProviderIds,DateCreated,UserDataPlayCount,UserDataLastPlayedDate",
                },
            )
            if data and "Items" in data:
                items.extend(data["Items"])
        logger.debug(f"Found {len(items)} items in Jellyfin with play data.")
        return items

    def find_item_by_provider_id(
        self, provider: str, provider_id: str
    ) -> dict[str, Any] | None:
        """Find a Jellyfin item by external provider ID (Imdb, Tmdb, Tvdb)."""
        data = self._get(
            "/Items",
            params={
                f"Any{provider}Id": provider_id,
                "Recursive": "true",
                "Fields": "ProviderIds",
            },
        )
        if data and data.get("Items"):
            return data["Items"][0]
        return None

    def find_season(
        self, series_jellyfin_id: str, season_number: int
    ) -> dict[str, Any] | None:
        """Find a specific season item within a Jellyfin series."""
        data = self._get(
            f"/Shows/{series_jellyfin_id}/Seasons",
        )
        if data and "Items" in data:
            for season in data["Items"]:
                if season.get("IndexNumber") == season_number:
                    return season
        return None

    def delete_item(self, item_id: str) -> bool:
        """Delete an item from Jellyfin's database."""
        logger.debug(f"Deleting Jellyfin item {item_id}")
        return self._delete(f"/Items/{item_id}")

    def refresh_library(self) -> bool:
        """Trigger a full library refresh."""
        logger.debug("Triggering Jellyfin library refresh...")
        return self._post("/Library/Refresh")
