"""Клиент REST API OpenSky Network.

Документация: https://openskynetwork.github.io/opensky-api/rest.html

Авторизация необязательна: без учётных данных клиент работает в анонимном
режиме, но с уменьшенными лимитами. Если заданы ``client_id`` и
``client_secret``, клиент получает OAuth2-токен и обновляет его автоматически.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from aviation.api.http_client import ApiError, HttpClient
from aviation.config import OpenSkyConfig
from aviation.models import Aeroplane, Country


class OpenSkyClient(HttpClient):
    """Клиент OpenSky для получения state vectors воздушных судов."""

    BASE_URL = "https://opensky-network.org/api"
    TOKEN_URL = (
        "https://auth.opensky-network.org/auth/realms/opensky-network/"
        "protocol/openid-connect/token"
    )
    TOKEN_REFRESH_MARGIN = 60

    def __init__(self, config: OpenSkyConfig, user_agent: str) -> None:
        """Инициализирует клиент OpenSky.

        :param config: параметры OpenSky (учётные данные, таймаут, пауза).
        :param user_agent: значение заголовка ``User-Agent``.
        """
        super().__init__(
            self.BASE_URL,
            user_agent,
            timeout=config.timeout,
            request_delay=config.request_delay,
        )
        self._client_id = config.client_id
        self._client_secret = config.client_secret
        self._token: str | None = None
        self._token_expires_at = 0.0

    def get_aeroplanes(self, country: Country) -> list[Aeroplane]:
        """Возвращает воздушные суда в воздушном пространстве страны.

        Запрос выполняется по bounding box страны. Суда, находящиеся на земле
        или без координат, пропускаются. Дубликаты по ``icao24`` устраняются.

        :param country: страна с координатами bounding box.
        :return: список воздушных судов в воздухе.
        :raises ApiError: если API вернул некорректный ответ.
        """
        params = {
            "lamin": country.min_latitude,
            "lamax": country.max_latitude,
            "lomin": country.min_longitude,
            "lomax": country.max_longitude,
        }
        payload = self.get_json(
            "/states/all",
            params=params,
            headers=self._auth_headers(),
        )
        if not isinstance(payload, dict):
            raise ApiError(
                f"Некорректный ответ OpenSky для страны {country.name}"
            )

        states = payload.get("states") or []
        aeroplanes: dict[str, Aeroplane] = {}
        for state in states:
            aeroplane = self._parse_state(state, country)
            if aeroplane is not None:
                aeroplanes[aeroplane.icao24] = aeroplane
        return list(aeroplanes.values())

    def _auth_headers(self) -> dict[str, str]:
        """Возвращает заголовок авторизации или пустой словарь.

        При наличии учётных данных получает OAuth2-токен и кэширует его
        до истечения срока действия.

        :return: словарь с заголовком ``Authorization`` либо пустой словарь.
        :raises ApiError: если не удалось получить токен.
        """
        if not self._client_id or not self._client_secret:
            return {}

        if self._token and time.monotonic() < self._token_expires_at:
            return {"Authorization": f"Bearer {self._token}"}

        payload = self.post_form_json(
            self.TOKEN_URL,
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise ApiError("OpenSky не вернул OAuth2-токен")

        expires_in = float(payload.get("expires_in", 1800))
        self._token = str(payload["access_token"])
        self._token_expires_at = time.monotonic() + max(
            expires_in - self.TOKEN_REFRESH_MARGIN,
            30.0,
        )
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _parse_state(state: Any, country: Country) -> Aeroplane | None:
        """Преобразует элемент ``states`` OpenSky в модель ``Aeroplane``.

        :param state: массив значений state vector из ответа API.
        :param country: страна, в воздушном пространстве которой найдено судно.
        :return: объект :class:`Aeroplane` или ``None``, если судно не в воздухе.
        """
        if not isinstance(state, list) or len(state) < 17:
            return None

        icao24 = str(state[0] or "").strip().lower()
        longitude = state[5]
        latitude = state[6]
        on_ground = state[8]
        last_contact = state[4] or state[3]

        if not icao24 or longitude is None or latitude is None:
            return None
        if on_ground is True or last_contact is None:
            return None

        callsign = str(state[1] or "").strip() or None
        squawk = str(state[14] or "").strip() or None
        time_position = state[3]
        sensors = state[12] if isinstance(state[12], list) else None
        category = state[17] if len(state) > 17 else None

        return Aeroplane(
            icao24=icao24,
            callsign=callsign,
            origin_country=state[2],
            time_position=(
                datetime.fromtimestamp(int(time_position), tz=timezone.utc)
                if time_position is not None
                else None
            ),
            last_contact=datetime.fromtimestamp(int(last_contact), tz=timezone.utc),
            longitude=float(longitude),
            latitude=float(latitude),
            baro_altitude=state[7],
            velocity=state[9],
            true_track=state[10],
            vertical_rate=state[11],
            on_ground=False,
            sensors=(
                [int(sensor) for sensor in sensors]
                if sensors is not None
                else None
            ),
            geo_altitude=state[13],
            squawk=squawk,
            spi=bool(state[15]) if state[15] is not None else False,
            position_source=state[16],
            category=category,
            country_iso_code=country.iso_code,
            country_name=country.name,
        )
