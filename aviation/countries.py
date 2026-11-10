"""Список стран, за воздушным пространством которых ведётся наблюдение.

Требование задания — не менее четырёх стран. Здесь выбрано двенадцать,
чтобы таблица ``countries`` гарантированно содержала больше десяти строк.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountryRef:
    """Ссылка на страну: название для поиска и ISO 3166-1 alpha-2 код."""

    name: str
    iso_code: str


TRACKED_COUNTRIES: tuple[CountryRef, ...] = (
    CountryRef(name="Germany", iso_code="DE"),
    CountryRef(name="France", iso_code="FR"),
    CountryRef(name="Spain", iso_code="ES"),
    CountryRef(name="Italy", iso_code="IT"),
    CountryRef(name="Poland", iso_code="PL"),
    CountryRef(name="Netherlands", iso_code="NL"),
    CountryRef(name="Belgium", iso_code="BE"),
    CountryRef(name="Austria", iso_code="AT"),
    CountryRef(name="Switzerland", iso_code="CH"),
    CountryRef(name="Czechia", iso_code="CZ"),
    CountryRef(name="Portugal", iso_code="PT"),
    CountryRef(name="Sweden", iso_code="SE"),
)
