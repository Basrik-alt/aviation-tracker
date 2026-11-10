"""Конфигурация приложения.

Все настройки читаются из переменных окружения (файл ``.env`` в корне
проекта). Значения по умолчанию позволяют запустить приложение локально
без дополнительной настройки, кроме параметров PostgreSQL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)

DEFAULT_USER_AGENT = "AviationCoursework/1.0 (+https://example.org/aviation-coursework)"


@dataclass(frozen=True)
class DatabaseConfig:
    """Параметры подключения к PostgreSQL."""

    host: str
    port: int
    name: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Создаёт конфигурацию БД из переменных окружения."""
        return cls(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            name=os.getenv("DB_NAME", "aviation"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
        )


@dataclass(frozen=True)
class NominatimConfig:
    """Параметры клиента Nominatim."""

    email: str | None
    request_delay: float

    @classmethod
    def from_env(cls) -> "NominatimConfig":
        """Создаёт конфигурацию Nominatim из переменных окружения."""
        return cls(
            email=os.getenv("NOMINATIM_EMAIL") or None,
            request_delay=float(os.getenv("NOMINATIM_REQUEST_DELAY", "1.1")),
        )


@dataclass(frozen=True)
class OpenSkyConfig:
    """Параметры клиента OpenSky Network."""

    client_id: str | None
    client_secret: str | None
    request_delay: float
    timeout: float

    @property
    def has_credentials(self) -> bool:
        """Возвращает ``True``, если заданы учётные данные OAuth2."""
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls) -> "OpenSkyConfig":
        """Создаёт конфигурацию OpenSky из переменных окружения."""
        return cls(
            client_id=os.getenv("OPENSKY_CLIENT_ID") or None,
            client_secret=os.getenv("OPENSKY_CLIENT_SECRET") or None,
            request_delay=float(os.getenv("OPENSKY_REQUEST_DELAY", "3.0")),
            timeout=float(os.getenv("OPENSKY_TIMEOUT", "60")),
        )


@dataclass(frozen=True)
class AppConfig:
    """Общая конфигурация приложения."""

    user_agent: str
    database: DatabaseConfig
    nominatim: NominatimConfig
    opensky: OpenSkyConfig

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Собирает полную конфигурацию из переменных окружения."""
        return cls(
            user_agent=os.getenv("APP_USER_AGENT", DEFAULT_USER_AGENT),
            database=DatabaseConfig.from_env(),
            nominatim=NominatimConfig.from_env(),
            opensky=OpenSkyConfig.from_env(),
        )
