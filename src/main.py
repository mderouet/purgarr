import time
from datetime import datetime

from croniter import croniter

from .config import (
    ConfigError,
    MEDIA_PATH,
    SPACE_MODE,
    FREE_SPACE_THRESHOLD_GB,
    AGE_MODE,
    MAX_AGE_DAYS,
    DRY_RUN,
    VERBOSE,
    CRON_SCHEDULE,
)
from .services.collector import DataCollector
from .services.analyzer import MediaAnalyzer
from .services.deleter import MediaDeleter
from .utils.logger import setup_logger


def run_once():
    """Execute a single run of the cleanup logic."""
    logger = setup_logger(verbose=VERBOSE)
    logger.info("--- Purgarr Run Started ---")
    logger.info(
        f"Config: space_mode={SPACE_MODE} ({FREE_SPACE_THRESHOLD_GB}GB), "
        f"age_mode={AGE_MODE} ({MAX_AGE_DAYS}d), dry_run={DRY_RUN}"
    )

    if not SPACE_MODE and not AGE_MODE:
        logger.warning("Both SPACE_MODE and AGE_MODE are disabled. Nothing to do.")
        return

    try:
        collector = DataCollector()
        analyzer = MediaAnalyzer()
        deleter = MediaDeleter()

        # Collect all media
        all_media = collector.collect_all_media()
        if not all_media:
            logger.info("No media found. Nothing to do.")
            return

        # Sort by deletion priority
        sorted_media = analyzer.sort_for_deletion(all_media)

        all_deleted = []

        # Age mode: delete everything older than MAX_AGE_DAYS
        if AGE_MODE:
            logger.info(f"Running age mode: deleting content older than {MAX_AGE_DAYS} days...")
            age_candidates = analyzer.filter_by_age(sorted_media, MAX_AGE_DAYS)
            if age_candidates:
                deleted = deleter.delete_list(age_candidates, DRY_RUN)
                all_deleted.extend(deleted)
                # Remove deleted items from sorted list for space mode
                deleted_set = set(id(m) for m in deleted)
                sorted_media = [m for m in sorted_media if id(m) not in deleted_set]

        # Space mode: delete until free > threshold
        if SPACE_MODE:
            logger.info(
                f"Running space mode: target {FREE_SPACE_THRESHOLD_GB} GB free..."
            )
            deleted = deleter.delete_for_space(
                sorted_media, FREE_SPACE_THRESHOLD_GB, MEDIA_PATH, DRY_RUN
            )
            all_deleted.extend(deleted)

        # Post-cleanup: refresh Plex + Jellyfin
        if all_deleted:
            deleter.post_cleanup(DRY_RUN)

        # Summary
        deleter.log_summary(all_deleted, DRY_RUN)

    except ConfigError as e:
        logger.error(f"Configuration Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)

    logger.info("--- Purgarr Run Finished ---")


def main():
    """Main entry point with optional cron scheduling."""
    logger = setup_logger(verbose=VERBOSE)
    logger.info("--- Purgarr Service Started ---")

    if not CRON_SCHEDULE:
        logger.info("No CRON_SCHEDULE set. Running once.")
        run_once()
        logger.info("--- Purgarr Service Finished ---")
        return

    logger.info(f"Scheduling runs with cron: '{CRON_SCHEDULE}'")

    # Run immediately on start, then follow schedule
    run_once()

    cron = croniter(CRON_SCHEDULE, datetime.now())
    while True:
        next_run = cron.get_next(datetime)
        sleep_seconds = (next_run - datetime.now()).total_seconds()
        if sleep_seconds > 0:
            logger.info(
                f"Next run: {next_run}. Sleeping {sleep_seconds / 3600:.1f}h."
            )
            time.sleep(sleep_seconds)
        run_once()


if __name__ == "__main__":
    main()
