import requests
from typing import Any

from ..config import RADARR_URL, RADARR_API_KEY
from ..utils.logger import setup_logger

logger = setup_logger()


class RadarrClient:
    """Client for interacting with the Radarr API."""

    def __init__(
        self, base_url: str = RADARR_URL, api_key: str = RADARR_API_KEY
    ):
        if not base_url or not api_key:
            raise ValueError("Radarr URL and API key must be provided.")
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
            logger.error(f"Radarr GET {endpoint} failed: {e}")
            return None

    def _delete(self, endpoint: str, params: dict[str, Any] | None = None) -> bool:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.delete(
                url, headers=self.headers, params=params, timeout=60
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Radarr DELETE {endpoint} failed: {e}")
            return False

    def get_all_movies(self) -> list[dict[str, Any]]:
        """Fetch all movies from Radarr."""
        logger.debug("Fetching all movies from Radarr...")
        data = self._get("/api/v3/movie")
        movies = data if isinstance(data, list) else []
        logger.debug(f"Found {len(movies)} movies in Radarr.")
        return movies

    def get_queue(self) -> list[dict[str, Any]]:
        """Fetch the current download queue."""
        data = self._get("/api/v3/queue", params={"pageSize": 100})
        if data and "records" in data:
            return data["records"]
        return []

    def get_history(self, movie_id: int) -> list[dict[str, Any]]:
        """Fetch download history for a movie (to get torrent hash)."""
        data = self._get(
            "/api/v3/history",
            params={
                "movieId": movie_id,
                "pageSize": 50,
            },
        )
        if not data or "records" not in data:
            return []
        # Safety: filter server-side results by movieId in case the API ignores the filter
        return [r for r in data["records"] if r.get("movieId") == movie_id]

    def delete_movie(self, radarr_id: int, delete_files: bool = True) -> bool:
        """Delete a movie from Radarr and optionally its files."""
        logger.debug(f"Deleting movie ID {radarr_id} (deleteFiles={delete_files})")
        return self._delete(
            f"/api/v3/movie/{radarr_id}",
            params={"deleteFiles": str(delete_files).lower()},
        )
