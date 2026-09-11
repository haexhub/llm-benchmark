from __future__ import annotations

import logging
import os

from rich.logging import RichHandler


def setup_logging(level: str | None = None) -> None:
    resolved = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    handler = RichHandler(rich_tracebacks=True, show_path=False, markup=False)
    logging.basicConfig(
        level=resolved,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[handler],
        force=True,
    )
