"""Structured logging: JSON outside local dev, with request/scan ids bound via contextvars."""

import logging
import sys

import structlog

from triage_core.settings import LogLevel


def configure_logging(level: LogLevel, *, json: bool) -> None:
    numeric_level = logging.getLevelNamesMapping()[level]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    # Third-party libraries (uvicorn, sqlalchemy, alembic) use stdlib logging.
    logging.basicConfig(level=numeric_level, format="%(levelname)s %(name)s %(message)s")
