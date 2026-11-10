"""Клиент публичного API Nominatim (OpenStreetMap).

Документация: https://nominatim.org/release-docs/latest/api/Search/
"""

from __future__ import annotations

from aviation.api.http_client import ApiError, HttpClient
from aviation.config import NominatimConfig
from aviation.countries import CountryRef
from aviation.models import Country


class NominatimClient(HttpClient):
    """Клиент Nominatim для получения координат и границ стран."""

    BASE_URL = "https://nominatim.openstreetmap.org"

    def __init__(self, config: NominatimConfig, user_agent: str) -> None:
        """Инициализирует клиент Nominatim.

        :param config: параметры Nominatim (e-mail и пауза между запросами).
        :param user_agent: значение заголовка ``User-Agent``.
        """
        super().__init__(
            self.BASE_URL,
            user_agent,
            timeout=30.0,
            request_delay=config.request_delay,
        )
        self._email = config.email
        self._session.headers["Accept-Language"] = "en"

    def get_country(self, country_ref: CountryRef) -> Country:
        """Возвращает страну с координатами и bounding box.

        :param country_ref: название страны и её ISO-код.
        :return: объект :class:`Country` с координатами центра и границами.
        :raises ApiError: если страна не найдена или ответ имеет неверный формат.
        """
        params: dict[str, str | int | float] = {
            "q": country_ref.name,
            "countrycodes": country_ref.iso_code.lower(),
            "format": "jsonv2",
            "limit": 1,
            "featureType": "country",
            "polygon_geojson": 1,
            "polygon_threshold": 0.01,
        }
        if self._email:
            params["email"] = self._email

        data = self.get_json("/search", params=params)
        if not isinstance(data, list) or not data:
            raise ApiError(
                f"Nominatim не нашёл страну {country_ref.name} "
                f"({country_ref.iso_code})"
            )

        item = data[0]
        try:
            south, north, west, east = (float(value) for value in item["boundingbox"])
            latitude = float(item["lat"])
            longitude = float(item["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(
                f"Некорректный ответ Nominatim для страны {country_ref.name}"
            ) from exc

        # Nominatim возвращает bounding box всех территорий страны. Для стран
        # с заморскими владениями (Франция, Испания, Португалия, Нидерланды)
        # такой bbox покрывает почти весь мир, поэтому для запроса в OpenSky
        # используется bbox крупнейшей части страны (материковой территории).
        main_bbox = None
        try:
            main_bbox = self._mainland_bbox(item.get("geojson"))
        except (TypeError, ValueError, IndexError):
            main_bbox = None
        if main_bbox is not None:
            south, north, west, east = main_bbox

        if south >= north or west >= east:
            raise ApiError(
                f"Некорректный bounding box для страны {country_ref.name}: "
                f"{item['boundingbox']}"
            )

        return Country(
            name=country_ref.name,
            iso_code=country_ref.iso_code.upper(),
            latitude=latitude,
            longitude=longitude,
            min_latitude=south,
            max_latitude=north,
            min_longitude=west,
            max_longitude=east,
        )

    @classmethod
    def _mainland_bbox(
        cls,
        geojson: object,
    ) -> tuple[float, float, float, float] | None:
        """Возвращает bbox крупнейшей части страны из GeoJSON.

        :param geojson: геометрия страны (``Polygon`` или ``MultiPolygon``).
        :return: кортеж ``(south, north, west, east)`` или ``None``, если
                 геометрию не удалось разобрать.
        """
        if not isinstance(geojson, dict):
            return None

        geometry_type = geojson.get("type")
        coordinates = geojson.get("coordinates")
        if not isinstance(coordinates, list):
            return None

        if geometry_type == "Polygon":
            polygons = [coordinates]
        elif geometry_type == "MultiPolygon":
            polygons = coordinates
        else:
            return None

        best_bbox: tuple[float, float, float, float] | None = None
        best_area = 0.0

        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                continue
            outer_ring = polygon[0]
            if not isinstance(outer_ring, list) or len(outer_ring) < 3:
                continue

            area = cls._ring_area(outer_ring)
            bbox = cls._ring_bbox(outer_ring)
            if bbox is not None and area > best_area:
                best_area = area
                best_bbox = bbox

        return best_bbox

    @staticmethod
    def _ring_area(ring: list[object]) -> float:
        """Вычисляет площадь внешнего кольца полигона (формула шнурков).

        :param ring: список точек ``[longitude, latitude, ...]``.
        :return: абсолютная площадь в квадратных градусах.
        """
        area = 0.0
        for index in range(len(ring) - 1):
            first = ring[index]
            second = ring[index + 1]
            if not isinstance(first, list) or not isinstance(second, list):
                continue
            area += first[0] * second[1] - second[0] * first[1]
        return abs(area) / 2.0

    @staticmethod
    def _ring_bbox(ring: list[object]) -> tuple[float, float, float, float] | None:
        """Вычисляет bbox внешнего кольца полигона.

        :param ring: список точек ``[longitude, latitude, ...]``.
        :return: кортеж ``(south, north, west, east)`` или ``None``.
        """
        longitudes: list[float] = []
        latitudes: list[float] = []
        for point in ring:
            if not isinstance(point, list) or len(point) < 2:
                continue
            longitudes.append(float(point[0]))
            latitudes.append(float(point[1]))

        if not longitudes or not latitudes:
            return None
        return (
            min(latitudes),
            max(latitudes),
            min(longitudes),
            max(longitudes),
        )

