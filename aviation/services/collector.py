"""Сервис сбора данных из внешних API и сохранения их в PostgreSQL."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from aviation.api.http_client import ApiError
from aviation.countries import CountryRef
from aviation.models import Aeroplane, Country
from aviation.services.protocols import (
    AeroplaneProvider,
    AeroplaneStorage,
    CountryProvider,
)


@dataclass(frozen=True)
class CollectionResult:
    """Результат загрузки данных."""

    countries: list[Country]
    aeroplanes_count: int
    failed_countries: list[str]


class DataCollector:
    """Собирает страны и воздушные суда и сохраняет их в БД.

    Сервис не знает, как именно устроены API-клиенты и база данных:
    он работает с ними через протоколы.
    """

    def __init__(
        self,
        country_provider: CountryProvider,
        aeroplane_provider: AeroplaneProvider,
        storage: AeroplaneStorage,
        country_refs: tuple[CountryRef, ...],
    ) -> None:
        """Инициализирует сервис сбора данных.

        :param country_provider: источник данных о странах (Nominatim).
        :param aeroplane_provider: источник данных о самолётах (OpenSky).
        :param storage: хранилище стран и самолётов (``DBManager``).
        :param country_refs: список стран, за которыми ведётся наблюдение.
        """
        self._country_provider = country_provider
        self._aeroplane_provider = aeroplane_provider
        self._storage = storage
        self._country_refs = country_refs
        self._logger = logging.getLogger(self.__class__.__name__)

    def run(self) -> CollectionResult:
        """Загружает данные и сохраняет их в базу.

        :return: результат загрузки.
        :raises RuntimeError: если не удалось получить ни одну страну.
        """
        countries, failed_countries = self._collect_countries()
        if not countries:
            raise RuntimeError(
                "Не удалось получить данные ни по одной стране. "
                "Проверьте подключение к интернету и доступность Nominatim."
            )

        self._storage.save_countries(countries)
        aeroplanes = self._collect_aeroplanes(countries)
        self._storage.replace_aeroplanes(aeroplanes)

        return CollectionResult(
            countries=countries,
            aeroplanes_count=len(aeroplanes),
            failed_countries=failed_countries,
        )

    def _collect_countries(self) -> tuple[list[Country], list[str]]:
        """Последовательно получает данные о странах из Nominatim.

        Ошибка по одной стране не прерывает загрузку остальных.

        :return: список стран и список названий стран с ошибками.
        """
        countries: list[Country] = []
        failed: list[str] = []

        for country_ref in self._country_refs:
            try:
                country = self._country_provider.get_country(country_ref)
            except ApiError as exc:
                self._logger.error(
                    "Не удалось получить данные о стране %s: %s",
                    country_ref.name,
                    exc,
                )
                failed.append(country_ref.name)
                continue

            self._logger.info(
                "Страна %s: bbox (%.3f, %.3f) — (%.3f, %.3f)",
                country.name,
                country.min_latitude,
                country.min_longitude,
                country.max_latitude,
                country.max_longitude,
            )
            countries.append(country)

        return countries, failed

    def _collect_aeroplanes(self, countries: list[Country]) -> list[Aeroplane]:
        """Получает воздушные суда для каждой страны из OpenSky.

        Ошибка по одной стране не прерывает загрузку остальных.

        :param countries: страны, для которых нужно получить самолёты.
        :return: список воздушных судов.
        """
        # bbox соседних стран пересекаются, поэтому одно и то же судно может
        # встретиться несколько раз. Оставляем запись той страны, к центру
        # которой самолёт ближе всего.
        aeroplanes: dict[str, tuple[Aeroplane, float]] = {}

        for country in countries:
            try:
                country_aeroplanes = self._aeroplane_provider.get_aeroplanes(country)
            except ApiError as exc:
                self._logger.error(
                    "Не удалось получить самолёты над страной %s: %s",
                    country.name,
                    exc,
                )
                continue

            self._logger.info(
                "Страна %s: найдено самолётов — %s",
                country.name,
                len(country_aeroplanes),
            )
            for aeroplane in country_aeroplanes:
                distance = self._distance_to_country(aeroplane, country)
                current = aeroplanes.get(aeroplane.icao24)
                if current is None or distance < current[1]:
                    aeroplanes[aeroplane.icao24] = (aeroplane, distance)

        return [aeroplane for aeroplane, _ in aeroplanes.values()]

    @staticmethod
    def _distance_to_country(aeroplane: Aeroplane, country: Country) -> float:
        """Возвращает квадрат расстояния от самолёта до центра страны.

        Используется для выбора страны, если bbox нескольких стран
        пересекаются.

        :param aeroplane: воздушное судно.
        :param country: страна с координатами центра.
        :return: квадрат расстояния в «квадратных градусах»; ``inf``, если
                 координаты самолёта неизвестны.
        """
        if aeroplane.latitude is None or aeroplane.longitude is None:
            return float("inf")

        latitude_scale = math.cos(math.radians(country.latitude))
        delta_latitude = aeroplane.latitude - country.latitude
        delta_longitude = (
            aeroplane.longitude - country.longitude
        ) * latitude_scale
        return delta_latitude**2 + delta_longitude**2
