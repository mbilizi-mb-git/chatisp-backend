import logging
import sys
from pathlib import Path

import structlog
from pythonjsonlogger import jsonlogger
from structlog.processors import JSONRenderer

from app.core.config import get_settings

settings = get_settings()


def configure_logging() -> None:
    """Configure structured JSON logging for the application."""

    # Ensure log directory exists
    log_file = Path(settings.LOG_FILE)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Create handlers
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    console_handler = logging.StreamHandler(sys.stdout)

    # 2. Set formatters
    # Console: plain text (simple)
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)

    # File: JSON formatter
    json_formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(json_formatter)

    # 3. Configure root logger with both handlers
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        handlers=[file_handler, console_handler],
    )

    # 4. Configure structlog to use standard logging with JSON renderer
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 5. Log a confirmation message (without keyword arguments)
    logging.getLogger().info(f"Logging configured | log_file={log_file} | level={settings.LOG_LEVEL}")


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger with the given name, configured as per the application settings.
    This function should be used throughout the application to obtain loggers.
    """
    return logging.getLogger(name)