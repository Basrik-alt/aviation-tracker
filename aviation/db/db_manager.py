"""Класс :class:`DBManager` для работы с данными в PostgreSQL.

Класс инкапсулирует подключение к базе данных, создание схемы, сохранение
стран и воздушных судов, а также выборки, требуемые заданием.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from aviation.config import DatabaseConfig
from aviation.models import Aeroplane, Country, CountryAeroplanesCount

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Условие, по которому считается средняя скорость. Используется и в
# get_avg_speed(), и в get_aeroplanes_with_higher_speed(), чтобы результаты
# этих методов были согласованы.
AVG_SPEED_CONDITION = "velocity IS NOT NULL AND velocity > 0 AND on_ground = FALSE"

AEROPLANE_SELECT = """
    SELECT a.*, c.name AS country_name, c.iso_code
    FROM aeroplanes AS a
    JOIN countries AS c ON c.id = a.country_id
"""


class DBManager:
    """Подключение к PostgreSQL и операции с таблицами стран и самолётов."""

    def __init__(self, config: DatabaseConfig) -> None:
        """Открывает соединение с базой данных.

        :param config: параметры подключения к PostgreSQL.
        :raises psycopg2.Error: если подключиться не удалось.
        """
        self._logger = logging.getLogger(self.__class__.__name__)
        self._connection = psycopg2.connect(
            host=config.host,
            port=config.port,
            dbname=config.name,
            user=config.user,
            password=config.password,
        )

    def close(self) -> None:
        """Закрывает соединение с базой данных."""
        if self._connection is not None and not self._connection.closed:
            self._connection.close()

    def __enter__(self) -> "DBManager":
        """Вход в контекстный менеджер."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Закрывает соединение при выходе из контекстного менеджера."""
        self.close()

    def create_tables(self) -> None:
        """Создаёт таблицы и индексы, если они ещё не существуют.

        SQL-схема читается из файла ``schema.sql``.
        """
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connection:
            with self._connection.cursor() as cursor:
                cursor.execute(schema)
        self._logger.info("Таблицы countries и aeroplanes готовы к работе")

    def save_countries(self, countries: Iterable[Country]) -> int:
        """Сохраняет страны в таблицу ``countries``.

        Существующие записи обновляются по ISO-коду страны.

        :param countries: список стран для сохранения.
        :return: количество обработанных строк.
        """
        rows = [
            (
                country.name,
                country.iso_code,
                country.latitude,
                country.longitude,
                country.min_latitude,
                country.max_latitude,
                country.min_longitude,
                country.max_longitude,
            )
            for country in countries
        ]
        if not rows:
            return 0

        query = """
            INSERT INTO countries (
                name,
                iso_code,
                latitude,
                longitude,
                min_latitude,
                max_latitude,
                min_longitude,
                max_longitude
            )
            VALUES %s
            ON CONFLICT (iso_code) DO UPDATE SET
                name = EXCLUDED.name,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                min_latitude = EXCLUDED.min_latitude,
                max_latitude = EXCLUDED.max_latitude,
                min_longitude = EXCLUDED.min_longitude,
                max_longitude = EXCLUDED.max_longitude
        """
        with self._connection:
            with self._connection.cursor() as cursor:
                execute_values(cursor, query, rows)
        self._logger.info("Сохранено стран: %s", len(rows))
        return len(rows)

    def save_aeroplanes(self, aeroplanes: Iterable[Aeroplane]) -> int:
        """Сохраняет воздушные суда в таблицу ``aeroplanes``.

        Записи обновляются по ``icao24``, поэтому повторная загрузка не
        создаёт дубликатов. Страны должны быть сохранены заранее.

        :param aeroplanes: список воздушных судов.
        :return: количество обработанных строк.
        :raises ValueError: если для судна не найдена страна в базе.
        """
        with self._connection:
            return self._insert_aeroplanes(aeroplanes)

    def replace_aeroplanes(self, aeroplanes: Iterable[Aeroplane]) -> int:
        """Заменяет все воздушные суда актуальным снимком воздушного пространства.

        Удаление старых строк и вставка новых выполняются в одной транзакции.

        :param aeroplanes: список воздушных судов.
        :return: количество вставленных строк.
        :raises ValueError: если для судна не найдена страна в базе.
        """
        with self._connection:
            with self._connection.cursor() as cursor:
                cursor.execute("DELETE FROM aeroplanes")
            return self._insert_aeroplanes(aeroplanes)

    def clear_aeroplanes(self) -> None:
        """Удаляет все записи из таблицы ``aeroplanes``."""
        with self._connection:
            with self._connection.cursor() as cursor:
                cursor.execute("DELETE FROM aeroplanes")
        self._logger.info("Таблица aeroplanes очищена")

    def get_countries_and_aeroplanes_count(self) -> list[CountryAeroplanesCount]:
        """Возвращает страны и количество самолётов в их воздушном пространстве.

        Используется ``LEFT JOIN``, поэтому страны без самолётов также
        попадают в результат (с количеством 0).

        :return: список пар «страна — количество самолётов».
        """
        query = """
            SELECT c.name AS country, COUNT(a.id) AS aeroplanes_count
            FROM countries AS c
            LEFT JOIN aeroplanes AS a ON a.country_id = c.id
            GROUP BY c.id, c.name
            ORDER BY c.name
        """
        with self._connection:
            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
        return [
            CountryAeroplanesCount(
                country=row["country"],
                aeroplanes_count=int(row["aeroplanes_count"]),
            )
            for row in rows
        ]

    def get_all_aeroplanes(self) -> list[Aeroplane]:
        """Возвращает список всех воздушных судов.

        :return: список самолётов, отсортированный по стране и позывному.
        """
        query = AEROPLANE_SELECT + """
            ORDER BY c.name, a.callsign NULLS LAST, a.icao24
        """
        return self._fetch_aeroplanes(query)

    def get_avg_speed(self) -> float | None:
        """Возвращает среднюю скорость воздушных судов в м/с.

        Учитываются только суда в воздухе с положительной скоростью.

        :return: средняя скорость или ``None``, если данных нет.
        """
        query = f"""
            SELECT AVG(velocity) AS avg_speed
            FROM aeroplanes
            WHERE {AVG_SPEED_CONDITION}
        """
        with self._connection:
            with self._connection.cursor() as cursor:
                cursor.execute(query)
                row = cursor.fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def get_aeroplanes_with_higher_speed(self) -> list[Aeroplane]:
        """Возвращает самолёты, скорость которых выше средней.

        Средняя скорость вычисляется тем же запросом, что и в
        :meth:`get_avg_speed`.

        :return: список самолётов, отсортированный по убыванию скорости.
        """
        query = AEROPLANE_SELECT + f"""
            WHERE a.velocity > (
                SELECT AVG(velocity)
                FROM aeroplanes
                WHERE {AVG_SPEED_CONDITION}
            )
            ORDER BY a.velocity DESC, a.callsign NULLS LAST
        """
        return self._fetch_aeroplanes(query)

    def get_aeroplanes_with_keyword(self, keyword: str) -> list[Aeroplane]:
        """Возвращает самолёты, в позывных которых есть указанные символы.

        Поиск выполняется без учёта регистра (``ILIKE``). Например,
        ``ACA`` найдёт самолёты авиакомпании Air Canada.

        :param keyword: искомая подстрока позывного.
        :return: список подходящих самолётов.
        :raises ValueError: если строка поиска пустая.
        """
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("Поисковая строка не должна быть пустой")

        escaped = (
            keyword.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        query = AEROPLANE_SELECT + """
            WHERE a.callsign ILIKE %s
            ORDER BY a.callsign, a.icao24
        """
        return self._fetch_aeroplanes(query, (f"%{escaped}%",))

    def _insert_aeroplanes(self, aeroplanes: Iterable[Aeroplane]) -> int:
        """Вставляет или обновляет воздушные суда в текущей транзакции.

        :param aeroplanes: список воздушных судов.
        :return: количество обработанных строк.
        :raises ValueError: если для судна не найдена страна в базе.
        """
        aeroplanes = list(aeroplanes)
        if not aeroplanes:
            return 0

        # Один и тот же самолёт может попасть в bbox нескольких стран.
        # Оставляем по одной записи на icao24, чтобы ON CONFLICT не обновил
        # одну и ту же строку дважды в рамках одного INSERT.
        unique_aeroplanes: dict[str, Aeroplane] = {}
        for aeroplane in aeroplanes:
            unique_aeroplanes.setdefault(aeroplane.icao24, aeroplane)
        if len(unique_aeroplanes) != len(aeroplanes):
            self._logger.info(
                "Удалено дубликатов по icao24: %s",
                len(aeroplanes) - len(unique_aeroplanes),
            )
        aeroplanes = list(unique_aeroplanes.values())

        country_ids = self._load_country_ids()
        missing = sorted(
            {
                aeroplane.country_iso_code or "<не указан>"
                for aeroplane in aeroplanes
                if not aeroplane.country_iso_code
                or aeroplane.country_iso_code not in country_ids
            }
        )
        if missing:
            raise ValueError(
                "Сначала сохраните страны в таблицу countries: "
                + ", ".join(missing)
            )

        rows = [
            (
                aeroplane.icao24,
                aeroplane.callsign,
                aeroplane.origin_country,
                aeroplane.time_position,
                aeroplane.last_contact,
                aeroplane.longitude,
                aeroplane.latitude,
                aeroplane.baro_altitude,
                aeroplane.velocity,
                aeroplane.true_track,
                aeroplane.vertical_rate,
                aeroplane.on_ground,
                aeroplane.sensors,
                aeroplane.geo_altitude,
                aeroplane.squawk,
                aeroplane.spi,
                aeroplane.position_source,
                aeroplane.category,
                country_ids[aeroplane.country_iso_code],
            )
            for aeroplane in aeroplanes
        ]

        query = """
            INSERT INTO aeroplanes (
                icao24,
                callsign,
                origin_country,
                time_position,
                last_contact,
                longitude,
                latitude,
                baro_altitude,
                velocity,
                true_track,
                vertical_rate,
                on_ground,
                sensors,
                geo_altitude,
                squawk,
                spi,
                position_source,
                category,
                country_id
            )
            VALUES %s
            ON CONFLICT (icao24) DO UPDATE SET
                callsign = EXCLUDED.callsign,
                origin_country = EXCLUDED.origin_country,
                time_position = EXCLUDED.time_position,
                last_contact = EXCLUDED.last_contact,
                longitude = EXCLUDED.longitude,
                latitude = EXCLUDED.latitude,
                baro_altitude = EXCLUDED.baro_altitude,
                velocity = EXCLUDED.velocity,
                true_track = EXCLUDED.true_track,
                vertical_rate = EXCLUDED.vertical_rate,
                on_ground = EXCLUDED.on_ground,
                sensors = EXCLUDED.sensors,
                geo_altitude = EXCLUDED.geo_altitude,
                squawk = EXCLUDED.squawk,
                spi = EXCLUDED.spi,
                position_source = EXCLUDED.position_source,
                category = EXCLUDED.category,
                country_id = EXCLUDED.country_id,
                updated_at = NOW()
        """
        with self._connection.cursor() as cursor:
            execute_values(cursor, query, rows, page_size=500)
        self._logger.info("Сохранено воздушных судов: %s", len(rows))
        return len(rows)

    def _load_country_ids(self) -> dict[str, int]:
        """Возвращает соответствие ISO-кода страны её идентификатору в БД.

        :return: словарь ``{iso_code: country_id}``.
        """
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT iso_code, id FROM countries")
            return {
                iso_code.strip(): country_id
                for iso_code, country_id in cursor.fetchall()
            }

    def _fetch_aeroplanes(
        self,
        query: str,
        params: Sequence[Any] | None = None,
    ) -> list[Aeroplane]:
        """Выполняет запрос и преобразует строки в модели ``Aeroplane``.

        :param query: SQL-запрос, возвращающий колонки таблицы ``aeroplanes``
                      и поля ``country_name``, ``iso_code``.
        :param params: параметры запроса.
        :return: список воздушных судов.
        """
        with self._connection:
            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [self._row_to_aeroplane(row) for row in rows]

    @staticmethod
    def _row_to_aeroplane(row: dict[str, Any]) -> Aeroplane:
        """Преобразует строку результата SQL в модель ``Aeroplane``.

        :param row: строка, содержащая поля таблицы ``aeroplanes``.
        :return: объект воздушного судна.
        """
        iso_code = row["iso_code"]
        return Aeroplane(
            icao24=row["icao24"],
            callsign=row["callsign"],
            origin_country=row["origin_country"],
            time_position=row["time_position"],
            last_contact=row["last_contact"],
            longitude=row["longitude"],
            latitude=row["latitude"],
            baro_altitude=row["baro_altitude"],
            velocity=row["velocity"],
            true_track=row["true_track"],
            vertical_rate=row["vertical_rate"],
            on_ground=row["on_ground"],
            sensors=row["sensors"],
            geo_altitude=row["geo_altitude"],
            squawk=row["squawk"],
            spi=row["spi"],
            position_source=row["position_source"],
            category=row["category"],
            country_iso_code=iso_code.strip() if iso_code else None,
            country_name=row["country_name"],
        )
