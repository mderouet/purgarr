from datetime import datetime, timezone

from ..api.radarr import RadarrClient
from ..api.sonarr import SonarrClient
from ..api.jellyfin import JellyfinClient
from ..api.plex import PlexClient
from ..models.media import Media, Movie, Season
from ..utils.logger import setup_logger

logger = setup_logger()


class DataCollector:
    """Collects media data from Radarr, Sonarr, Jellyfin, and Plex."""

    def __init__(self):
        self.radarr = RadarrClient()
        self.sonarr = SonarrClient()
        self.jellyfin = JellyfinClient()
        self.plex = PlexClient()

    def collect_all_media(self) -> list[Media]:
        """Collect all deletable media units (movies + seasons)."""
        logger.debug("Starting data collection...")

        movies = self._collect_movies()
        seasons = self._collect_seasons()
        all_media: list[Media] = movies + seasons

        self._enrich_with_jellyfin_play_data(all_media)
        self._enrich_with_plex_play_data(all_media)

        logger.info(
            f"Collection complete: {len(movies)} movies, {len(seasons)} seasons."
        )
        return all_media

    def _collect_movies(self) -> list[Movie]:
        """Build Movie list from Radarr API."""
        raw_movies = self.radarr.get_all_movies()
        movies = []

        for raw in raw_movies:
            size = raw.get("sizeOnDisk", 0)
            if size <= 0:
                continue

            movie_file = raw.get("movieFile") or {}
            date_added = self._parse_date(movie_file.get("dateAdded"))

            movie = Movie(
                title=raw.get("title", "Unknown"),
                added_date=date_added,
                file_size=size,
                radarr_id=raw.get("id"),
                imdb_id=raw.get("imdbId"),
                tmdb_id=raw.get("tmdbId"),
            )
            movies.append(movie)

        logger.info(f"Collected {len(movies)} movies with files on disk.")
        return movies

    def _collect_seasons(self) -> list[Season]:
        """Build Season list from Sonarr API (one Season per series season with files)."""
        raw_series = self.sonarr.get_all_series()
        seasons = []

        for series in raw_series:
            series_id = series.get("id")
            series_title = series.get("title", "Unknown")
            imdb_id = series.get("imdbId")
            tvdb_id = series.get("tvdbId")

            # Get per-season stats from series data
            series_seasons = series.get("seasons", [])

            # Get actual episode files for this series
            episode_files = self.sonarr.get_episode_files(series_id)
            # Get episodes for unmonitoring
            episodes = self.sonarr.get_episodes(series_id)

            # Group episode files by season number
            files_by_season: dict[int, list[dict]] = {}
            for ef in episode_files:
                sn = ef.get("seasonNumber", 0)
                files_by_season.setdefault(sn, []).append(ef)

            # Group episode IDs by season number
            episodes_by_season: dict[int, list[int]] = {}
            for ep in episodes:
                sn = ep.get("seasonNumber", 0)
                ep_id = ep.get("id")
                if ep_id:
                    episodes_by_season.setdefault(sn, []).append(ep_id)

            for season_data in series_seasons:
                season_number = season_data.get("seasonNumber", 0)
                stats = season_data.get("statistics", {})
                size_on_disk = stats.get("sizeOnDisk", 0)

                if size_on_disk <= 0 or season_number == 0:
                    continue  # Skip specials and seasons with no files

                season_files = files_by_season.get(season_number, [])
                if not season_files:
                    continue

                file_ids = [f["id"] for f in season_files]
                episode_ids = episodes_by_season.get(season_number, [])

                # Use earliest file dateAdded as the season's added_date
                dates = [
                    self._parse_date(f.get("dateAdded"))
                    for f in season_files
                    if f.get("dateAdded")
                ]
                added_date = min(dates) if dates else None

                season = Season(
                    title=f"{series_title} - Season {season_number}",
                    added_date=added_date,
                    file_size=size_on_disk,
                    sonarr_series_id=series_id,
                    series_title=series_title,
                    season_number=season_number,
                    episode_file_ids=file_ids,
                    episode_ids=episode_ids,
                    imdb_id=imdb_id,
                    tvdb_id=tvdb_id,
                )
                seasons.append(season)

        logger.info(f"Collected {len(seasons)} seasons with files on disk.")
        return seasons

    def _enrich_with_jellyfin_play_data(self, media_list: list[Media]) -> None:
        """Enrich media items with Jellyfin PlayCount and LastPlayedDate."""
        try:
            jf_items = self.jellyfin.get_all_items_with_play_data()
        except Exception as e:
            logger.warning(f"Failed to get Jellyfin play data (non-fatal): {e}")
            return

        # Build lookup by IMDb ID
        jf_by_imdb: dict[str, dict] = {}
        for item in jf_items:
            provider_ids = item.get("ProviderIds", {})
            imdb = provider_ids.get("Imdb")
            if imdb:
                jf_by_imdb[imdb] = item

        matched = 0
        for media in media_list:
            imdb_id = None
            if isinstance(media, Movie):
                imdb_id = media.imdb_id
            elif isinstance(media, Season):
                imdb_id = media.imdb_id

            if not imdb_id or imdb_id not in jf_by_imdb:
                continue

            jf_item = jf_by_imdb[imdb_id]
            user_data = jf_item.get("UserData", {})
            media.jellyfin_id = jf_item.get("Id")
            media.play_count = user_data.get("PlayCount", 0)
            last_played = user_data.get("LastPlayedDate")
            if last_played:
                media.last_played_date = self._parse_date(last_played)
            matched += 1

        logger.info(f"Enriched {matched}/{len(media_list)} items with Jellyfin play data.")

    def _enrich_with_plex_play_data(self, media_list: list[Media]) -> None:
        """Enrich media items with Plex viewCount and lastViewedAt.

        Merges with existing Jellyfin data: keeps the most recent
        last_played_date from either source, and sums play counts.
        """
        if not self.plex.enabled:
            return

        try:
            plex_items = self.plex.get_all_items_with_play_data()
        except Exception as e:
            logger.warning(f"Failed to get Plex play data (non-fatal): {e}")
            return

        # Build lookup by IMDb ID
        plex_by_imdb: dict[str, dict] = {}
        for item in plex_items:
            imdb_id = PlexClient.extract_imdb_id(item)
            if imdb_id:
                plex_by_imdb[imdb_id] = item

        matched = 0
        for media in media_list:
            imdb_id = None
            if isinstance(media, Movie):
                imdb_id = media.imdb_id
            elif isinstance(media, Season):
                imdb_id = media.imdb_id

            if not imdb_id or imdb_id not in plex_by_imdb:
                continue

            plex_item = plex_by_imdb[imdb_id]
            media.plex_id = str(plex_item.get("ratingKey", ""))

            plex_view_count = plex_item.get("viewCount", 0)
            plex_last_viewed = plex_item.get("lastViewedAt")

            # Convert Plex epoch seconds to datetime
            plex_last_played: datetime | None = None
            if plex_last_viewed:
                plex_last_played = datetime.fromtimestamp(
                    plex_last_viewed, tz=timezone.utc
                )

            # Merge: keep the most recent last_played_date from either source
            if plex_last_played:
                if (
                    media.last_played_date is None
                    or plex_last_played > media.last_played_date
                ):
                    media.last_played_date = plex_last_played

            # Sum play counts from both sources
            media.play_count += plex_view_count

            matched += 1

        logger.info(
            f"Enriched {matched}/{len(media_list)} items with Plex play data."
        )

    def _parse_date(self, date_str: str | None) -> datetime | None:
        """Parse an ISO 8601 date string."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.debug(f"Could not parse date: {date_str}")
            return None
