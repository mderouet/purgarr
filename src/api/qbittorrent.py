import requests
from typing import Any

from ..config import QBITTORRENT_URL, QBITTORRENT_USERNAME, QBITTORRENT_PASSWORD
from ..utils.logger import setup_logger

logger = setup_logger()


class QBittorrentClient:
    """Client for interacting with the qBittorrent Web API v2."""

    def __init__(
        self,
        base_url: str = QBITTORRENT_URL,
        username: str = QBITTORRENT_USERNAME,
        password: str = QBITTORRENT_PASSWORD,
    ):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.username = username
        self.password = password
        self.enabled = bool(self.base_url)
        self.session = requests.Session()
        self._authenticated = False

        if not self.enabled:
            logger.info("qBittorrent integration disabled (no URL configured).")

    def _authenticate(self) -> bool:
        """Authenticate with qBittorrent to get a session cookie."""
        if self._authenticated:
            return True
        if not self.enabled:
            return False

        try:
            response = self.session.post(
                f"{self.base_url}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=10,
            )
            if response.text == "Ok.":
                self._authenticated = True
                logger.debug("Authenticated with qBittorrent.")
                return True
            logger.error(f"qBittorrent auth failed: {response.text}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"qBittorrent auth error: {e}")
            return False

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> Any | None:
        if not self._authenticate():
            return None
        try:
            response = self.session.get(
                f"{self.base_url}{endpoint}", params=params, timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"qBittorrent GET {endpoint} failed: {e}")
            return None

    def _post(self, endpoint: str, data: dict[str, Any] | None = None) -> bool:
        if not self._authenticate():
            return False
        try:
            response = self.session.post(
                f"{self.base_url}{endpoint}", data=data, timeout=30
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"qBittorrent POST {endpoint} failed: {e}")
            return False

    def delete_torrent(self, torrent_hash: str, delete_files: bool = True) -> bool:
        """Delete a torrent and optionally its files."""
        if not self.enabled:
            return False
        logger.info(
            f"Deleting torrent {torrent_hash[:8]}... "
            f"(deleteFiles={delete_files})"
        )
        return self._post(
            "/api/v2/torrents/delete",
            data={
                "hashes": torrent_hash,
                "deleteFiles": str(delete_files).lower(),
            },
        )

    def delete_torrents_by_hashes(
        self, hashes: list[str], delete_files: bool = True
    ) -> bool:
        """Delete multiple torrents by their hashes."""
        if not self.enabled or not hashes:
            return True
        joined = "|".join(hashes)
        logger.debug(f"Deleting {len(hashes)} torrents from qBittorrent...")
        return self._post(
            "/api/v2/torrents/delete",
            data={"hashes": joined, "deleteFiles": str(delete_files).lower()},
        )
