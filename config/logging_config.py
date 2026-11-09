import inspect
import logging
import sys
from loguru import logger
from config.settings import settings


class InterceptHandler(logging.Handler):
    """
    Route stdlib logging records into loguru.
    The ingestion modules use logging.getLogger(__name__); without this,
    their INFO lines (including the run summary) would never be shown.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk back past logging's own frames so loguru reports the real caller
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

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

    # Send every stdlib logger through loguru; loguru's sinks apply LOG_LEVEL
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    logger.info("Logging initialised — level={}", settings.LOG_LEVEL)
    logger.info("Log file: {}", log_file)