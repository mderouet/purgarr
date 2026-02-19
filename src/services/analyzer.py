from datetime import datetime, timedelta, timezone

from ..models.media import Media
from ..utils.logger import setup_logger

logger = setup_logger()

# Items played in the last N days are deprioritized (moved to end of list)
RECENT_PLAY_DAYS = 30


class MediaAnalyzer:
    """Analyzes and sorts media for deletion priority."""

    def sort_for_deletion(self, media_list: list[Media]) -> list[Media]:
        """
        Sort media by deletion priority: oldest added_date first,
        with recently-played items deprioritized to the end.
        """
        if not media_list:
            return []

        recent_threshold = datetime.now(timezone.utc) - timedelta(days=RECENT_PLAY_DAYS)

        recently_played = []
        not_recently_played = []

        for media in media_list:
            if (
                media.last_played_date
                and media.last_played_date > recent_threshold
            ):
                recently_played.append(media)
            else:
                not_recently_played.append(media)

        # Sort each group by added_date (oldest first)
        # Items with no added_date go first (unknown age = delete first)
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        not_recently_played.sort(key=lambda m: m.added_date or epoch)
        recently_played.sort(key=lambda m: m.added_date or epoch)

        logger.info(
            f"Sorted {len(not_recently_played)} items by age, "
            f"{len(recently_played)} recently-played items deprioritized."
        )

        return not_recently_played + recently_played

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
