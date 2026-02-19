import shutil

from ..utils.logger import setup_logger

logger = setup_logger()


def get_free_space_gb(path: str) -> float | None:
    """
    Returns the free disk space in GB for the given path.

    Args:
        path: The filesystem path to check.

    Returns:
        Free space in GB, or None if an error occurs.
    """
    try:
        total, used, free = shutil.disk_usage(path)
        if total == 0:
            logger.warning(f"Total disk space reported as zero for path: {path}")
            return 0.0

        free_gb = free / (1024**3)
        logger.debug(f"Disk free space for '{path}': {free_gb:.2f} GB")
        return free_gb
    except FileNotFoundError:
        logger.error(f"Error getting disk usage: The path '{path}' does not exist.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting disk usage for '{path}': {e}")
        return None
