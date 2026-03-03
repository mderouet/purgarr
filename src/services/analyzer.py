from datetime import datetime, timezone

from ..models.media import Media
from ..utils.logger import setup_logger

logger = setup_logger()


class MediaAnalyzer:
    """Analyzes and sorts media for deletion priority."""

    def sort_for_deletion(self, media_list: list[Media]) -> list[Media]:
        """
        Sort media by deletion priority using a "relevance date" approach.

        The relevance date is:
          - last_played_date if the item has been watched
          - added_date if the item has never been watched

        Sort ascending (oldest relevance date first = delete first).
        This naturally produces:
          1. Watched long ago          → delete first
          2. Never watched, added long ago → delete next
          3. Never watched, added recently → protect
          4. Watched recently           → protect most
        """
        if not media_list:
            return []

        epoch = datetime.min.replace(tzinfo=timezone.utc)

        def relevance_date(media: Media) -> datetime:
            if media.last_played_date:
                return media.last_played_date
            return media.added_date or epoch

        sorted_list = sorted(media_list, key=relevance_date)

        watched = sum(1 for m in media_list if m.last_played_date)
        unwatched = len(media_list) - watched
        logger.debug(
            f"Sorted {len(media_list)} items by relevance date "
            f"({watched} watched, {unwatched} unwatched)."
        )

        return sorted_list

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
