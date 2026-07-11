"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import Optional


_LOGGERS: dict[str, logging.Logger] = {}


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    component: str = "cadengine",
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional path to a log file.
        component: Root logger name.
    """
    logger = logging.getLogger(component)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="w")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _LOGGERS[component] = logger


def get_logger(name: str) -> logging.Logger:
    """Get a named logger.

    The logger is a child of the root component logger so that
    log levels propagate correctly.

    Args:
        name: Subcomponent name, e.g. 'cad.parser' or 'heating.rooms'.

    Returns:
        A configured logger instance.
    """
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(f"cadengine.{name}")
    _LOGGERS[name] = logger
    return logger
