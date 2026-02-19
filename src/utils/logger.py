import logging
import sys


def setup_logger(verbose: bool = False) -> logging.Logger:
    """
    Set up and configure the application logger.

    Args:
        verbose: If True, the log level is set to DEBUG. Otherwise, INFO.

    Returns:
        A configured logger instance.
    """
    log_level = logging.DEBUG if verbose else logging.INFO

    logger = logging.getLogger("purgarr")
    logger.setLevel(log_level)

    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
