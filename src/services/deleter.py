from tabulate import tabulate

from ..api.radarr import RadarrClient
from ..api.sonarr import SonarrClient
from ..api.jellyfin import JellyfinClient
from ..api.plex import PlexClient
from ..api.qbittorrent import QBittorrentClient
from ..models.media import Media, Movie, Season
from ..utils.disk import get_free_space_gb
from ..utils.logger import setup_logger

logger = setup_logger()


class MediaDeleter:
    """Handles deletion of media across all services."""

    def __init__(self):
        self.radarr = RadarrClient()
        self.sonarr = SonarrClient()
        self.jellyfin = JellyfinClient()
        self.plex = PlexClient()
        self.qbt = QBittorrentClient()

    def delete_for_space(
        self,
        sorted_media: list[Media],
        threshold_gb: float,
        media_path: str,
        dry_run: bool,
    ) -> list[Media]:
        """Delete items until free space > threshold_gb (space mode)."""
        free = get_free_space_gb(media_path)
        if free is None:
            logger.error(f"Cannot read disk space for {media_path}. Aborting.")
            return []

        if free >= threshold_gb:
            logger.info(
                f"Free space {free:.2f} GB >= {threshold_gb} GB threshold. "
                "No deletion needed."
            )
            return []

        logger.info(
            f"Free space {free:.2f} GB < {threshold_gb} GB threshold. "
            "Starting space-based cleanup..."
        )

        deleted = []
        for media in sorted_media:
            free = get_free_space_gb(media_path)
            if free is not None and free >= threshold_gb:
                logger.info("Free space is now above threshold. Stopping.")
                break

            if self._delete_media(media, dry_run):
                deleted.append(media)

        return deleted

    def delete_list(
        self, media_list: list[Media], dry_run: bool
    ) -> list[Media]:
        """Delete all items in the list (age mode)."""
        deleted = []
        for media in media_list:
            if self._delete_media(media, dry_run):
                deleted.append(media)
        return deleted

    def _delete_media(self, media: Media, dry_run: bool) -> bool:
        """Delete a single media item from all services."""
        size_gb = media.file_size / (1024**3)

        if dry_run:
            logger.info(f"[DRY RUN] Would delete '{media.title}' ({size_gb:.2f} GB)")
            return True

        logger.info(f"Deleting '{media.title}' ({size_gb:.2f} GB)...")

        if isinstance(media, Movie):
            return self._delete_movie(media)
        elif isinstance(media, Season):
            return self._delete_season(media)
        else:
            logger.warning(f"Unknown media type for '{media.title}'")
            return False

    def _delete_movie(self, movie: Movie) -> bool:
        """Delete a movie: Radarr → qBittorrent → Jellyfin."""
        if not movie.radarr_id:
            logger.warning(f"No Radarr ID for '{movie.title}', skipping.")
            return False

        # 1. Get torrent hashes from Radarr history BEFORE deleting
        torrent_hashes = self._get_radarr_torrent_hashes(movie.radarr_id)

        # 2. Delete from Radarr (removes library files)
        if not self.radarr.delete_movie(movie.radarr_id, delete_files=True):
            logger.error(f"Failed to delete '{movie.title}' from Radarr.")
            return False

        # 3. Clean up download files via qBittorrent
        if torrent_hashes:
            self.qbt.delete_torrents_by_hashes(torrent_hashes)

        # 4. Remove from Jellyfin
        self._delete_from_jellyfin_movie(movie)

        logger.info(f"Successfully deleted movie '{movie.title}'.")
        return True

    def _delete_season(self, season: Season) -> bool:
        """Delete a season: unmonitor → delete files → clean up series → qBT → Jellyfin."""
        if not season.sonarr_series_id or not season.episode_file_ids:
            logger.warning(f"No Sonarr data for '{season.title}', skipping.")
            return False

        # 1. Get torrent hashes from Sonarr history BEFORE deleting
        torrent_hashes = self._get_sonarr_torrent_hashes(
            season.sonarr_series_id, season.season_number
        )

        # 2. Unmonitor episodes FIRST (prevents Sonarr re-search race)
        if season.episode_ids:
            self.sonarr.unmonitor_episodes(season.episode_ids)

        # 3. Delete episode files
        all_deleted = True
        for file_id in season.episode_file_ids:
            if not self.sonarr.delete_episode_file(file_id):
                logger.error(f"Failed to delete episode file {file_id}")
                all_deleted = False

        if not all_deleted:
            logger.error(f"Some files failed to delete for '{season.title}'.")
            return False

        # 4. Check if series is now empty → delete entire series
        self._cleanup_empty_series(season.sonarr_series_id)

        # 5. Clean up download files via qBittorrent
        if torrent_hashes:
            self.qbt.delete_torrents_by_hashes(torrent_hashes)

        # 6. Remove from Jellyfin
        self._delete_from_jellyfin_season(season)

        logger.info(f"Successfully deleted '{season.title}'.")
        return True

    def _cleanup_empty_series(self, series_id: int) -> None:
        """If a series has no remaining episode files, delete it from Sonarr."""
        remaining_files = self.sonarr.get_episode_files(series_id)
        if not remaining_files:
            logger.info(
                f"Series {series_id} has no remaining files. "
                "Deleting entire series from Sonarr."
            )
            self.sonarr.delete_series(series_id, delete_files=True)

    def _get_radarr_torrent_hashes(self, movie_id: int) -> list[str]:
        """Extract torrent hashes from Radarr download history."""
        history = self.radarr.get_history(movie_id)
        hashes = set()
        for record in history:
            dl_id = record.get("downloadId")
            if dl_id:
                hashes.add(dl_id.lower())
        return list(hashes)

    def _get_sonarr_torrent_hashes(
        self, series_id: int, season_number: int
    ) -> list[str]:
        """Extract torrent hashes from Sonarr download history for a season."""
        history = self.sonarr.get_history(series_id)
        hashes = set()
        for record in history:
            episode = record.get("episode", {})
            if episode.get("seasonNumber") == season_number:
                dl_id = record.get("downloadId")
                if dl_id:
                    hashes.add(dl_id.lower())
        return list(hashes)

    def _delete_from_jellyfin_movie(self, movie: Movie) -> None:
        """Remove a movie from Jellyfin's database."""
        if movie.jellyfin_id:
            self.jellyfin.delete_item(movie.jellyfin_id)
            return

        # Try to find by IMDb ID
        if movie.imdb_id:
            item = self.jellyfin.find_item_by_provider_id("Imdb", movie.imdb_id)
            if item:
                self.jellyfin.delete_item(item["Id"])
                return

        logger.debug(f"Could not find '{movie.title}' in Jellyfin to clean up.")

    def _delete_from_jellyfin_season(self, season: Season) -> None:
        """Remove a season from Jellyfin's database."""
        # First find the series in Jellyfin
        series_jf = None
        if season.imdb_id:
            series_jf = self.jellyfin.find_item_by_provider_id("Imdb", season.imdb_id)
        if not series_jf and season.tvdb_id:
            series_jf = self.jellyfin.find_item_by_provider_id(
                "Tvdb", str(season.tvdb_id)
            )

        if not series_jf:
            logger.debug(
                f"Could not find series '{season.series_title}' in Jellyfin."
            )
            return

        # Find and delete the specific season
        jf_season = self.jellyfin.find_season(
            series_jf["Id"], season.season_number
        )
        if jf_season:
            self.jellyfin.delete_item(jf_season["Id"])
        else:
            logger.debug(
                f"Could not find season {season.season_number} of "
                f"'{season.series_title}' in Jellyfin."
            )

    def post_cleanup(self, dry_run: bool) -> None:
        """Run post-deletion cleanup: Plex refresh, Jellyfin refresh."""
        if dry_run:
            logger.info("[DRY RUN] Would refresh Plex and Jellyfin libraries.")
            return

        self.plex.refresh_and_clean()
        self.jellyfin.refresh_library()

    @staticmethod
    def log_summary(deleted_items: list[Media], dry_run: bool) -> None:
        """Log a summary table of what was deleted."""
        action = "would be" if dry_run else "were"

        if not deleted_items:
            logger.info("No items were deleted.")
            return

        total_freed = sum(m.file_size for m in deleted_items)
        headers = ["Title", "Type", "Size (GB)", "Added Date"]
        rows = []
        for item in deleted_items:
            added = item.added_date.date() if item.added_date else "Unknown"
            rows.append([
                item.title,
                item.__class__.__name__,
                f"{item.file_size / (1024**3):.2f}",
                added,
            ])

        summary = "Dry Run Summary" if dry_run else "Deletion Summary"
        logger.info(f"\n--- {summary} ---")
        logger.info(f"\n{tabulate(rows, headers=headers, tablefmt='grid')}\n")
        logger.info(
            f"{len(deleted_items)} items {action} deleted. "
            f"Total space {action} freed: {total_freed / (1024**3):.2f} GB."
        )
