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
        """Delete multiple torrents by their hashes.

        Deletes as a batch first, then verifies all were removed.
        Any survivors are retried individually.
        """
        if not self.enabled or not hashes:
            return True

        # Batch delete
        joined = "|".join(hashes)
        logger.debug(f"Deleting {len(hashes)} torrents from qBittorrent...")
        success = self._post(
            "/api/v2/torrents/delete",
            data={"hashes": joined, "deleteFiles": str(delete_files).lower()},
        )
        if not success:
            logger.error("qBittorrent batch delete API call failed.")

        # Verify deletion — some torrents may silently survive
        survivors = self.verify_torrents_deleted(hashes)
        if not survivors:
            return True

        # Retry survivors individually
        logger.warning(
            f"{len(survivors)} torrent(s) survived batch delete, "
            "retrying individually..."
        )
        for h in survivors:
            ok = self._post(
                "/api/v2/torrents/delete",
                data={"hashes": h, "deleteFiles": str(delete_files).lower()},
            )
            if not ok:
                logger.error(f"Individual delete failed for torrent {h[:8]}")

        # Final verification — check ALL retried hashes, not just API failures,
        # because qBittorrent can return 200 OK without actually deleting
        final_survivors = self.verify_torrents_deleted(survivors)
        if final_survivors:
            short = ", ".join(h[:8] for h in final_survivors)
            logger.error(
                f"{len(final_survivors)} torrent(s) could not be deleted "
                f"from qBittorrent: {short}"
            )
            return False

        return True

    def get_all_torrents(self) -> list[dict[str, Any]]:
        """Fetch all torrents from qBittorrent."""
        if not self.enabled:
            return []
        data = self._get("/api/v2/torrents/info")
        return data if isinstance(data, list) else []

    def find_torrents_by_content_path(
        self, path_substring: str
    ) -> list[dict[str, Any]]:
        """Find torrents whose content_path or save_path contains the substring."""
        if not self.enabled or not path_substring:
            return []
        torrents = self.get_all_torrents()
        needle = path_substring.lower()
        return [
            t for t in torrents
            if needle in (t.get("content_path", "").lower())
            or needle in (t.get("save_path", "").lower())
            or needle in (t.get("name", "").lower())
        ]

    def verify_torrents_deleted(self, hashes: list[str]) -> list[str]:
        """Check which of the given hashes still exist in qBittorrent.

        Returns a list of hashes that are still present (survivors).
        """
        if not self.enabled or not hashes:
            return []
        torrents = self.get_all_torrents()
        existing = {t["hash"].lower() for t in torrents}
        return [h for h in hashes if h.lower() in existing]
