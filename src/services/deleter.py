from tabulate import tabulate

from ..api.radarr import RadarrClient
from ..api.sonarr import SonarrClient
from ..api.jellyfin import JellyfinClient
from ..api.plex import PlexClient
from ..api.qbittorrent import QBittorrentClient
from ..api.seerr import SeerrClient
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
        self.seerr = SeerrClient()
        self._media_path = ""

    def delete_for_space(
        self,
        sorted_media: list[Media],
        threshold_gb: float,
        media_path: str,
        dry_run: bool,
    ) -> list[Media]:
        """Delete items until free space > threshold_gb (space mode)."""
        self._media_path = media_path
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
            "Starting cleanup..."
        )

        deleted = []
        for media in sorted_media:
            free = get_free_space_gb(media_path)
            if free is not None and free >= threshold_gb:
                logger.info(
                    f"Free space {free:.2f} GB is now above threshold. Stopping."
                )
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
        added = media.added_date.strftime("%Y-%m-%d") if media.added_date else "unknown"
        last_played = media.last_played_date.strftime("%Y-%m-%d") if media.last_played_date else "never"

        watch_info = ""
        if isinstance(media, Season) and media.total_episodes > 0:
            watch_info = f", {media.watched_episodes}/{media.total_episodes} eps watched"
        elif isinstance(media, Movie) and media.play_count > 0:
            watch_info = f", viewed x{media.play_count}"

        desc = f"'{media.title}' ({size_gb:.2f} GB, added {added}, last played {last_played}{watch_info})"

        if dry_run:
            logger.info(f"[DRY RUN] Would delete {desc}")
            return True

        logger.info(f"Deleting {desc}...")

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

        free_before = get_free_space_gb(self._media_path)

        # 1. Get torrent hashes from Radarr history BEFORE deleting
        torrent_hashes = self._get_radarr_torrent_hashes(movie.radarr_id)

        # 2. Delete from Radarr (removes library files)
        if not self.radarr.delete_movie(movie.radarr_id, delete_files=True):
            logger.error(f"  Radarr: FAILED to delete movie #{movie.radarr_id}")
            return False
        logger.info(f"  Radarr: deleted movie #{movie.radarr_id}")

        # 3. Clean up download files via qBittorrent
        self._cleanup_qbt_torrents(torrent_hashes, movie.title)

        # 4. Remove from Jellyfin
        jf_id = self._delete_from_jellyfin_movie(movie)
        if jf_id:
            logger.info(f"  Jellyfin: deleted item {jf_id[:12]}")
        else:
            logger.info("  Jellyfin: item not found (already removed or not indexed)")

        self._log_disk_delta(free_before)

        return True

    def _delete_season(self, season: Season) -> bool:
        """Delete a season: unmonitor → delete files → clean up series → qBT → Jellyfin."""
        if not season.sonarr_series_id or not season.episode_file_ids:
            logger.warning(f"No Sonarr data for '{season.title}', skipping.")
            return False

        free_before = get_free_space_gb(self._media_path)

        # 1. Get torrent hashes from Sonarr history BEFORE deleting
        torrent_hashes = self._get_sonarr_torrent_hashes(
            season.sonarr_series_id, season.season_number, season.episode_ids
        )

        # 2. Unmonitor episodes FIRST (prevents Sonarr re-search race)
        if season.episode_ids:
            self.sonarr.unmonitor_episodes(season.episode_ids)

        # 3. Delete episode files
        num_files = len(season.episode_file_ids)
        all_deleted = True
        for file_id in season.episode_file_ids:
            if not self.sonarr.delete_episode_file(file_id):
                logger.error(f"  Sonarr: FAILED to delete episode file {file_id}")
                all_deleted = False

        if not all_deleted:
            logger.error(f"  Sonarr: some files failed to delete for '{season.title}'.")
            return False

        logger.info(
            f"  Sonarr: unmonitored {len(season.episode_ids)} episodes, "
            f"deleted {num_files} files from series #{season.sonarr_series_id}"
        )

        # 4. Check if series is now empty → delete entire series
        self._cleanup_empty_series(season.sonarr_series_id)

        # 5. Clean up download files via qBittorrent
        self._cleanup_qbt_torrents(torrent_hashes, season.series_title)

        # 6. Remove from Jellyfin
        jf_id = self._delete_from_jellyfin_season(season)
        if jf_id:
            logger.info(f"  Jellyfin: deleted season item {jf_id[:12]}")
        else:
            logger.info("  Jellyfin: season not found (already removed or not indexed)")

        self._log_disk_delta(free_before)

        return True

    def _cleanup_qbt_torrents(
        self, torrent_hashes: list[str], search_name: str
    ) -> None:
        """Delete torrents from qBittorrent using history hashes, with fallback.

        If history-based hashes are available, deletes them (with verification).
        If no hashes found in history, falls back to searching qBittorrent
        by content name to find orphaned torrents.
        """
        if torrent_hashes:
            short_hashes = ", ".join(h[:8] for h in torrent_hashes)
            ok = self.qbt.delete_torrents_by_hashes(torrent_hashes)
            if ok:
                logger.info(
                    f"  qBittorrent: deleted {len(torrent_hashes)} torrent(s) "
                    f"(hash: {short_hashes})"
                )
            else:
                logger.error(
                    f"  qBittorrent: FAILED to delete some torrent(s) "
                    f"(hash: {short_hashes})"
                )
        else:
            logger.info(
                "  qBittorrent: no torrents found in history, "
                "searching by content name..."
            )
            self._fallback_qbt_search(search_name)

    def _fallback_qbt_search(self, search_name: str) -> None:
        """Search qBittorrent for torrents matching the media name and delete them."""
        matches = self.qbt.find_torrents_by_content_path(search_name)
        if not matches:
            logger.info(
                f"  qBittorrent: no matching torrents found for '{search_name}'"
            )
            return

        hashes = [t["hash"] for t in matches]
        names = [t.get("name", "?") for t in matches]
        logger.info(
            f"  qBittorrent: found {len(matches)} torrent(s) by name search: "
            + ", ".join(names)
        )
        ok = self.qbt.delete_torrents_by_hashes(hashes)
        if ok:
            logger.info(
                f"  qBittorrent: deleted {len(hashes)} torrent(s) via fallback"
            )
        else:
            logger.error(
                "  qBittorrent: FAILED to delete torrents found via fallback"
            )

    def _log_disk_delta(self, free_before: float | None) -> None:
        """Log disk space change after a deletion and warn if nothing was freed."""
        free_after = get_free_space_gb(self._media_path)
        if free_before is None or free_after is None:
            return

        logger.info(f"  Disk: {free_before:.2f} -> {free_after:.2f} GB free")

        delta = free_after - free_before
        if delta < 0.01:
            logger.warning(
                "  Deletion freed 0 bytes — download files may still exist "
                "(hardlink or qBittorrent cleanup failed)"
            )

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
        logger.debug(
            f"Found {len(hashes)} torrent hash(es) for Radarr movie {movie_id} "
            f"from {len(history)} history record(s)."
        )
        return list(hashes)

    def _get_sonarr_torrent_hashes(
        self, series_id: int, season_number: int,
        episode_ids: list[int] | None = None,
    ) -> list[str]:
        """Extract torrent hashes from Sonarr download history for a season."""
        history = self.sonarr.get_history(series_id)
        hashes = set()
        episode_id_set = set(episode_ids) if episode_ids else set()
        for record in history:
            # Primary: match by episodeId (reliable top-level field)
            if episode_id_set and record.get("episodeId") in episode_id_set:
                dl_id = record.get("downloadId")
                if dl_id:
                    hashes.add(dl_id.lower())
            # Fallback: match by nested episode.seasonNumber
            elif not episode_id_set:
                episode = record.get("episode", {})
                if episode.get("seasonNumber") == season_number:
                    dl_id = record.get("downloadId")
                    if dl_id:
                        hashes.add(dl_id.lower())
        logger.debug(
            f"Found {len(hashes)} torrent hash(es) for Sonarr series {series_id} "
            f"season {season_number} from {len(history)} history record(s)."
        )
        return list(hashes)

    def _delete_from_jellyfin_movie(self, movie: Movie) -> str | None:
        """Remove a movie from Jellyfin's database. Returns the deleted item ID."""
        if movie.jellyfin_id:
            if self.jellyfin.delete_item(movie.jellyfin_id):
                return movie.jellyfin_id
            return None

        # Try to find by IMDb ID
        if movie.imdb_id:
            item = self.jellyfin.find_item_by_provider_id("Imdb", movie.imdb_id)
            if item and self.jellyfin.delete_item(item["Id"]):
                return item["Id"]

        logger.debug(f"Could not find '{movie.title}' in Jellyfin to clean up.")
        return None

    def _delete_from_jellyfin_season(self, season: Season) -> str | None:
        """Remove a season from Jellyfin's database. Returns the deleted item ID."""
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
            return None

        # Find and delete the specific season
        jf_season = self.jellyfin.find_season(
            series_jf["Id"], season.season_number
        )
        if jf_season:
            if self.jellyfin.delete_item(jf_season["Id"]):
                return jf_season["Id"]
            return None

        logger.debug(
            f"Could not find season {season.season_number} of "
            f"'{season.series_title}' in Jellyfin."
        )
        return None

    def post_cleanup(self, dry_run: bool) -> None:
        """Run post-deletion cleanup: Plex refresh, Jellyfin refresh."""
        if dry_run:
            logger.info("[DRY RUN] Would refresh Plex and Jellyfin libraries.")
            return

        logger.info("Refreshing Plex, Jellyfin, and Seerr libraries...")
        self.plex.refresh_and_clean()
        self.jellyfin.refresh_library()
        self.seerr.trigger_availability_sync()

    @staticmethod
    def log_summary(
        deleted_items: list[Media],
        dry_run: bool,
        disk_before_gb: float | None = None,
        disk_after_gb: float | None = None,
    ) -> None:
        """Log a summary table of what was deleted."""
        action = "would be" if dry_run else "were"

        if not deleted_items:
            logger.info("No items were deleted.")
            return

        total_file_size = sum(m.file_size for m in deleted_items)
        headers = ["Title", "Type", "Size (GB)", "Added Date", "Last Played", "Watch"]
        rows = []
        for item in deleted_items:
            added = item.added_date.date() if item.added_date else "Unknown"
            last_played = item.last_played_date.date() if item.last_played_date else "Never"
            if isinstance(item, Season) and item.total_episodes > 0:
                watch = f"{item.watched_episodes}/{item.total_episodes} eps"
            elif isinstance(item, Movie) and item.play_count > 0:
                watch = f"x{item.play_count}"
            else:
                watch = "-"
            rows.append([
                item.title,
                item.__class__.__name__,
                f"{item.file_size / (1024**3):.2f}",
                added,
                last_played,
                watch,
            ])

        summary = "Dry Run Summary" if dry_run else "Deletion Summary"
        logger.info(f"\n--- {summary} ---")
        logger.info(f"\n{tabulate(rows, headers=headers, tablefmt='grid')}\n")

        size_msg = f"File sizes: {total_file_size / (1024**3):.2f} GB"
        if disk_before_gb is not None and disk_after_gb is not None:
            actual_freed = disk_after_gb - disk_before_gb
            size_msg += f". Actual disk freed: {actual_freed:.2f} GB"
            if total_file_size > 0:
                ratio = (actual_freed * (1024**3)) / total_file_size
                if ratio < 0.5:
                    logger.warning(
                        f"Only {ratio:.0%} of file sizes were actually freed — "
                        "some download files may be orphaned on disk."
                    )

        logger.info(
            f"{len(deleted_items)} items {action} deleted. {size_msg}."
        )
