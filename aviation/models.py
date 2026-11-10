"""Доменные модели приложения.

Модели не зависят от источников данных и слоя хранения: их используют
и API-клиенты, и класс :class:`aviation.db.db_manager.DBManager`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Country:
    """Страна и её географические координаты.

    Прямоугольник ``min_latitude .. max_latitude`` /
    ``min_longitude .. max_longitude`` описывает bounding box страны,
    который используется для запроса воздушного пространства в OpenSky.
    """

    name: str
    iso_code: str
    latitude: float
    longitude: float
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float


@dataclass(frozen=True)
class Aeroplane:
    """Воздушное судно (state vector) в воздушном пространстве страны.

    Значения полей соответствуют ответу OpenSky ``/states/all``.
    Скорость (``velocity``) хранится в метрах в секунду, высоты — в метрах,
    углы — в градусах.
    """

    icao24: str
    callsign: str | None
    origin_country: str | None
    time_position: datetime | None
    last_contact: datetime
    longitude: float | None
    latitude: float | None
    baro_altitude: float | None
    velocity: float | None
    true_track: float | None
    vertical_rate: float | None
    on_ground: bool | None
    sensors: list[int] | None
    geo_altitude: float | None
    squawk: str | None
    spi: bool | None
    position_source: int | None
    category: int | None
    country_iso_code: str | None = None
    country_name: str | None = None


@dataclass(frozen=True)
class CountryAeroplanesCount:
    """Количество воздушных судов в воздушном пространстве страны."""

    country: str
    aeroplanes_count: int

    def __iter__(self) -> Iterator[str | int]:
        """Позволяет распаковывать результат как ``(страна, количество)``."""
        yield self.country
        yield self.aeroplanes_count
