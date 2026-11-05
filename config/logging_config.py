import sys
from loguru import logger
from config.settings import settings

def setup_logging() -> None:
    """
    Configure logging for the entire application.
    Call this once at startup — not in every file.
    All modules then use: from loguru import logger
    """
    logger.remove()

    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}:{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )

    log_file = settings.LOG_DIR / "mosaic_drishti.log"
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_file,
        level=settings.LOG_LEVEL,
        colorize=False,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{name}:{line} | "
            "{message}"
        ),
        rotation="10 MB",
        retention="30 days",
        compression="zip",
    )

    logger.info("Logging initialised — level={}", settings.LOG_LEVEL)
    logger.info("Log file: {}", log_file)