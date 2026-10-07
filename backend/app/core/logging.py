"""Logging configuration.

Stdlib logging with a structured, greppable format for Phase 1. The
call-site contract (what gets logged per backtest run) is defined in
docs/ARCHITECTURE.md §9; structlog can replace the formatter later without
changing call sites.
"""
import logging
import logging.config


def configure_logging(level: str = "INFO") -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": (
                        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
                    ),
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                }
            },
            "root": {"level": level.upper(), "handlers": ["console"]},
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
