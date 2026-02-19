import requests
from typing import Any

from ..config import SONARR_URL, SONARR_API_KEY
from ..utils.logger import setup_logger

logger = setup_logger()


class SonarrClient:
    """Client for interacting with the Sonarr API."""

    def __init__(
        self, base_url: str = SONARR_URL, api_key: str = SONARR_API_KEY
    ):
        if not base_url or not api_key:
            raise ValueError("Sonarr URL and API key must be provided.")
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any | None:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Sonarr GET {endpoint} failed: {e}")
            return None

    def _delete(self, endpoint: str, params: dict[str, Any] | None = None) -> bool:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.delete(
                url, headers=self.headers, params=params, timeout=120
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Sonarr DELETE {endpoint} failed: {e}")
            return False

    def _put(self, endpoint: str, json_data: Any = None) -> bool:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.put(
                url, headers=self.headers, json=json_data, timeout=30
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Sonarr PUT {endpoint} failed: {e}")
            return False

    def get_all_series(self) -> list[dict[str, Any]]:
        """Fetch all TV series from Sonarr."""
        logger.info("Fetching all series from Sonarr...")
        data = self._get("/api/v3/series")
        series = data if isinstance(data, list) else []
        logger.info(f"Found {len(series)} series in Sonarr.")
        return series

    def get_episode_files(self, series_id: int) -> list[dict[str, Any]]:
        """Fetch all episode files for a series."""
        data = self._get("/api/v3/episodefile", params={"seriesId": series_id})
        return data if isinstance(data, list) else []

    def get_episodes(self, series_id: int) -> list[dict[str, Any]]:
        """Fetch all episodes for a series (for unmonitoring)."""
        data = self._get("/api/v3/episode", params={"seriesId": series_id})
        return data if isinstance(data, list) else []

    def get_queue(self) -> list[dict[str, Any]]:
        """Fetch the current download queue."""
        data = self._get("/api/v3/queue", params={"pageSize": 100})
        if data and "records" in data:
            return data["records"]
        return []

    def get_history(self, series_id: int) -> list[dict[str, Any]]:
        """Fetch download history for a series (to get torrent hashes)."""
        data = self._get(
            "/api/v3/history",
            params={"seriesId": series_id, "pageSize": 200},
        )
        if data and "records" in data:
            return data["records"]
        return []

    def unmonitor_episodes(self, episode_ids: list[int]) -> bool:
        """Unmonitor a list of episodes by their IDs."""
        if not episode_ids:
            return True
        logger.info(f"Unmonitoring {len(episode_ids)} episodes...")
        return self._put(
            "/api/v3/episode/monitor",
            json_data={"episodeIds": episode_ids, "monitored": False},
        )

    def delete_episode_file(self, file_id: int) -> bool:
        """Delete a single episode file from disk."""
        logger.debug(f"Deleting episode file ID {file_id}")
        return self._delete(f"/api/v3/episodefile/{file_id}")

    def delete_series(self, series_id: int, delete_files: bool = True) -> bool:
        """Delete an entire series from Sonarr."""
        logger.warning(f"Deleting series ID {series_id} (deleteFiles={delete_files})")
        return self._delete(
            f"/api/v3/series/{series_id}",
            params={"deleteFiles": str(delete_files).lower()},
        )
