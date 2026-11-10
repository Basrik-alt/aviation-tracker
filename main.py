"""Точка входа приложения.

Примеры запуска:
    python main.py init-db
    python main.py load
    python main.py report --keyword ACA
"""

from __future__ import annotations

import sys

from aviation.cli import main


def _configure_stdout() -> None:
    """Включает UTF-8 для корректного вывода кириллицы в консоли Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass


if __name__ == "__main__":
    _configure_stdout()
    raise SystemExit(main())
