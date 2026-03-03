from datetime import datetime, timedelta, timezone

from tabulate import tabulate

from ..models.media import Media, Movie, Season
from ..utils.logger import setup_logger

logger = setup_logger()


class MediaAnalyzer:
    """Analyzes and sorts media for deletion priority."""

    def sort_for_deletion(self, media_list: list[Media]) -> list[Media]:
        """
        Sort media by deletion priority using a multi-tier approach.

        Tier 0: Fully watched seasons  (all episodes viewed) → delete first
        Tier 1: Fully watched movies   (play_count > 0)      → delete next
        Tier 2: Everything else                               → delete last

        Within each tier, sort by relevance date ascending (oldest first):
          - last_played_date if the item has been watched
          - added_date if never watched
        """
        if not media_list:
            return []

        epoch = datetime.min.replace(tzinfo=timezone.utc)

        def sort_key(media: Media) -> tuple:
            # Tier assignment
            if isinstance(media, Season) and media.is_fully_watched:
                tier = 0
            elif isinstance(media, Movie) and media.is_fully_watched:
                tier = 1
            else:
                tier = 2

            relevance = media.last_played_date or media.added_date or epoch
            return (tier, relevance)

        sorted_list = sorted(media_list, key=sort_key)

        # Log summary
        fully_watched = sum(1 for m in media_list if m.is_fully_watched)
        watched = sum(
            1 for m in media_list
            if m.last_played_date and not m.is_fully_watched
        )
        unwatched = len(media_list) - fully_watched - watched
        logger.debug(
            f"Sorted {len(media_list)} items: "
            f"{fully_watched} fully watched, {watched} partially watched, "
            f"{unwatched} unwatched."
        )

        return sorted_list

    def log_deletion_order(self, sorted_media: list[Media]) -> None:
        """Log a table showing the deletion priority order with reasoning."""
        if not sorted_media:
            return

        headers = ["#", "Title", "Type", "Size", "Watch Status", "Relevance Date"]
        rows = []
        for i, media in enumerate(sorted_media, 1):
            size = f"{media.file_size / (1024**3):.1f}GB"

            if isinstance(media, Season):
                if media.total_episodes > 0:
                    watch = f"{media.watched_episodes}/{media.total_episodes} eps"
                    if media.is_fully_watched:
                        watch += " (DONE)"
                else:
                    watch = "no data"
            else:  # Movie
                if media.play_count > 0:
                    watch = f"viewed x{media.play_count} (DONE)"
                elif media.last_played_date:
                    watch = "started"
                else:
                    watch = "unwatched"

            relevance = media.last_played_date or media.added_date
            rel_str = relevance.strftime("%Y-%m-%d") if relevance else "unknown"

            rows.append([i, media.title, media.__class__.__name__, size, watch, rel_str])

        logger.info(
            f"\n--- Deletion Priority Order ---\n"
            f"{tabulate(rows, headers=headers, tablefmt='simple')}\n"
        )

    def filter_by_age(
        self, media_list: list[Media], max_age_days: int
    ) -> list[Media]:
        """Filter to only items older than max_age_days (for age mode)."""
        threshold = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        old_items = [
            m for m in media_list
            if m.added_date and m.added_date < threshold
        ]
        logger.info(
            f"Age filter: {len(old_items)}/{len(media_list)} items "
            f"older than {max_age_days} days."
        )
        return old_items
