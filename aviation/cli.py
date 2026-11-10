"""Командный интерфейс приложения.

Команды:
    init-db  — создать таблицы в PostgreSQL;
    load     — загрузить страны и самолёты из внешних API;
    report   — вывести отчёты по данным из базы.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

import psycopg2

from aviation.api.http_client import ApiError
from aviation.api.nominatim_client import NominatimClient
from aviation.api.opensky_client import OpenSkyClient
from aviation.config import AppConfig
from aviation.countries import TRACKED_COUNTRIES
from aviation.db.db_manager import DBManager
from aviation.models import Aeroplane
from aviation.services.collector import DataCollector

LOGGER = logging.getLogger("aviation")


def _build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер аргументов командной строки.

    :return: настроенный парсер.
    """
    parser = argparse.ArgumentParser(
        prog="aviation",
        description=(
            "Отслеживание воздушных судов по данным OpenSky Network "
            "с сохранением в PostgreSQL."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="уровень логирования (по умолчанию INFO)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "init-db",
        help="создать таблицы countries и aeroplanes",
    )

    subparsers.add_parser(
        "load",
        help="загрузить данные из Nominatim и OpenSky в базу",
    )

    report = subparsers.add_parser(
        "report",
        help="показать отчёты по данным из базы",
    )
    report.add_argument(
        "--keyword",
        default="ACA",
        help="подстрока позывного для поиска (по умолчанию ACA)",
    )
    report.add_argument(
        "--limit",
        type=int,
        default=20,
        help="сколько строк показывать в подробных отчётах (по умолчанию 20)",
    )

    return parser


def _init_db(config: AppConfig) -> int:
    """Создаёт таблицы в базе данных.

    :param config: конфигурация приложения.
    :return: код возврата.
    """
    with DBManager(config.database) as db:
        db.create_tables()
    print("Таблицы countries и aeroplanes созданы (или уже существовали).")
    return 0


def _load(config: AppConfig) -> int:
    """Загружает данные из внешних API и сохраняет их в базу.

    :param config: конфигурация приложения.
    :return: код возврата.
    """
    with DBManager(config.database) as db:
        db.create_tables()
        with (
            NominatimClient(config.nominatim, config.user_agent) as nominatim,
            OpenSkyClient(config.opensky, config.user_agent) as opensky,
        ):
            collector = DataCollector(
                country_provider=nominatim,
                aeroplane_provider=opensky,
                storage=db,
                country_refs=TRACKED_COUNTRIES,
            )
            result = collector.run()

    print()
    print(f"Стран загружено:      {len(result.countries)}")
    print(f"Самолётов сохранено:  {result.aeroplanes_count}")
    if result.failed_countries:
        print(
            "Не удалось получить данные: "
            + ", ".join(result.failed_countries)
        )
    return 0


def _report(config: AppConfig, keyword: str, limit: int) -> int:
    """Выводит отчёты по данным из базы.

    :param config: конфигурация приложения.
    :param keyword: подстрока для поиска по позывным.
    :param limit: максимальное количество строк в подробных отчётах.
    :return: код возврата.
    """
    limit = max(limit, 1)

    with DBManager(config.database) as db:
        counts = db.get_countries_and_aeroplanes_count()
        all_aeroplanes = db.get_all_aeroplanes()
        avg_speed = db.get_avg_speed()
        faster = db.get_aeroplanes_with_higher_speed()
        by_keyword = db.get_aeroplanes_with_keyword(keyword)

    _print_title("1. Страны и количество самолётов в их воздушном пространстве")
    _print_table(
        ["Страна", "Самолётов"],
        [[row.country, row.aeroplanes_count] for row in counts],
    )

    _print_title("2. Средняя скорость самолётов")
    if avg_speed is None:
        print("Нет данных о скорости.")
    else:
        print(f"{avg_speed:.2f} м/с ({avg_speed * 3.6:.2f} км/ч)")

    _print_title("3. Самолёты со скоростью выше средней")
    print(f"Всего: {len(faster)}")
    if faster:
        _print_table(*_aeroplane_table(faster[:limit]))
        if len(faster) > limit:
            print(f"Показаны первые {limit} из {len(faster)}.")

    _print_title(f"4. Поиск по позывному: «{keyword}»")
    print(f"Всего: {len(by_keyword)}")
    if by_keyword:
        _print_table(*_aeroplane_table(by_keyword[:limit]))
        if len(by_keyword) > limit:
            print(f"Показаны первые {limit} из {len(by_keyword)}.")

    _print_title("5. Все воздушные суда")
    print(f"Всего: {len(all_aeroplanes)}")
    if all_aeroplanes:
        _print_table(*_aeroplane_table(all_aeroplanes[:limit]))
        if len(all_aeroplanes) > limit:
            print(f"Показаны первые {limit} из {len(all_aeroplanes)}.")

    return 0


def _aeroplane_table(
    aeroplanes: Sequence[Aeroplane],
) -> tuple[list[str], list[list[str]]]:
    """Формирует заголовки и строки таблицы для списка самолётов.

    :param aeroplanes: список воздушных судов.
    :return: заголовки и строки таблицы.
    """
    headers = [
        "ICAO24",
        "Позывной",
        "Страна",
        "Скорость, м/с",
        "Высота, м",
        "Широта",
        "Долгота",
    ]
    rows = [
        [
            aeroplane.icao24,
            aeroplane.callsign or "—",
            aeroplane.country_name or "—",
            _format_number(aeroplane.velocity, 1),
            _format_number(
                aeroplane.baro_altitude
                if aeroplane.baro_altitude is not None
                else aeroplane.geo_altitude,
                0,
            ),
            _format_number(aeroplane.latitude, 4),
            _format_number(aeroplane.longitude, 4),
        ]
        for aeroplane in aeroplanes
    ]
    return headers, rows


def _format_number(value: float | None, digits: int) -> str:
    """Форматирует число для вывода в таблице.

    :param value: число или ``None``.
    :param digits: количество знаков после запятой.
    :return: строка с числом или прочерк.
    """
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _print_title(title: str) -> None:
    """Печатает заголовок раздела.

    :param title: текст заголовка.
    """
    print()
    print(title)
    print("=" * len(title))


def _print_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
) -> None:
    """Печатает таблицу с выравниванием по ширине колонок.

    :param headers: заголовки колонок.
    :param rows: строки таблицы.
    """
    string_rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(str(header)) for header in headers]
    for row in string_rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))

    header_line = "  ".join(
        str(header).ljust(widths[index])
        for index, header in enumerate(headers)
    )
    print(header_line)
    print("-" * len(header_line))
    for row in string_rows:
        print(
            "  ".join(
                cell.ljust(widths[index])
                for index, cell in enumerate(row)
                if index < len(widths)
            )
        )


def main(argv: list[str] | None = None) -> int:
    """Точка входа командного интерфейса.

    :param argv: аргументы командной строки (по умолчанию ``sys.argv[1:]``).
    :return: код возврата процесса.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = AppConfig.from_env()
        if args.command == "init-db":
            return _init_db(config)
        if args.command == "load":
            return _load(config)
        return _report(config, args.keyword, args.limit)
    except (ApiError, psycopg2.Error, RuntimeError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
