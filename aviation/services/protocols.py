"""Протоколы зависимостей сервисного слоя.

Сервис сбора данных зависит от абстракций, а не от конкретных классов
API-клиентов и :class:`DBManager`. Это упрощает замену реализаций
и тестирование (принцип инверсии зависимостей).
"""

from __future__ import annotations

from typing import Protocol

from aviation.countries import CountryRef
from aviation.models import Aeroplane, Country


class CountryProvider(Protocol):
    """Источник данных о странах."""

    def get_country(self, country_ref: CountryRef) -> Country:
        """Возвращает страну с координатами и границами."""
        ...


class AeroplaneProvider(Protocol):
    """Источник данных о воздушных судах."""

    def get_aeroplanes(self, country: Country) -> list[Aeroplane]:
        """Возвращает воздушные суда в воздушном пространстве страны."""
        ...


class AeroplaneStorage(Protocol):
    """Хранилище стран и воздушных судов."""

    def save_countries(self, countries: list[Country]) -> int:
        """Сохраняет страны и возвращает количество обработанных строк."""
        ...

    def replace_aeroplanes(self, aeroplanes: list[Aeroplane]) -> int:
        """Заменяет воздушные суда и возвращает количество вставленных строк."""
        ...
