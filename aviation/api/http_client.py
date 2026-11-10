"""Базовый HTTP-клиент для работы с внешними API.

Класс инкапсулирует общую для всех клиентов логику: сессию ``requests``,
ограничение частоты запросов и повторные попытки при временных ошибках.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests


class ApiError(RuntimeError):
    """Ошибка при обращении к внешнему API."""


class HttpClient:
    """HTTP-клиент с ограничением частоты запросов и повторными попытками."""

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        *,
        timeout: float = 30.0,
        request_delay: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        """Инициализирует клиент.

        :param base_url: базовый адрес API.
        :param user_agent: значение заголовка ``User-Agent``.
        :param timeout: таймаут одного запроса в секундах.
        :param request_delay: минимальная пауза между запросами в секундах.
        :param max_retries: максимальное количество попыток одного запроса.
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._request_delay = max(request_delay, 0.0)
        self._max_retries = max(max_retries, 1)
        self._last_request_at = 0.0
        self._logger = logging.getLogger(self.__class__.__name__)

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Выполняет GET-запрос к API и возвращает декодированный JSON.

        :param path: путь относительно ``base_url``.
        :param params: query-параметры запроса.
        :param headers: дополнительные заголовки запроса.
        :return: декодированный ответ API.
        :raises ApiError: если запрос не удался или ответ не является JSON.
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        return self._request_json("GET", url, params=params, headers=headers)

    def post_form_json(self, url: str, data: dict[str, Any]) -> Any:
        """Выполняет POST-запрос с form-data и возвращает JSON.

        Используется для получения OAuth2-токена OpenSky.

        :param url: абсолютный адрес запроса.
        :param data: поля формы.
        :return: декодированный ответ API.
        :raises ApiError: если запрос не удался или ответ не является JSON.
        """
        return self._request_json("POST", url, data=data)

    def close(self) -> None:
        """Закрывает HTTP-сессию и освобождает соединения."""
        self._session.close()

    def __enter__(self) -> "HttpClient":
        """Вход в контекстный менеджер."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Закрывает сессию при выходе из контекстного менеджера."""
        self.close()

    def _request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        """Выполняет HTTP-запрос с повторами и возвращает JSON.

        :param method: HTTP-метод (``GET`` или ``POST``).
        :param url: абсолютный адрес запроса.
        :param kwargs: дополнительные аргументы ``requests``.
        :return: декодированный ответ API.
        :raises ApiError: если все попытки завершились ошибкой.
        """
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self._session.request(
                    method,
                    url,
                    timeout=self._timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_error = exc
                self._logger.warning(
                    "Сетевая ошибка (попытка %s из %s): %s",
                    attempt,
                    self._max_retries,
                    exc,
                )
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise ApiError(f"Ответ {url} не является корректным JSON") from exc

                message = (
                    f"HTTP {response.status_code} от {url}: "
                    f"{response.text[:300].strip()}"
                )
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = ApiError(message)
                    self._logger.warning(
                        "Временная ошибка (попытка %s из %s): %s",
                        attempt,
                        self._max_retries,
                        message,
                    )
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        time.sleep(min(int(retry_after), 60))
                else:
                    raise ApiError(message)

            if attempt < self._max_retries:
                time.sleep(min(2**attempt, 30))

        raise ApiError(f"Не удалось получить данные от {url}") from last_error

    def _respect_rate_limit(self) -> None:
        """Выдерживает паузу, если с прошлого запроса прошло мало времени."""
        elapsed = time.monotonic() - self._last_request_at
        wait_time = self._request_delay - elapsed
        if wait_time > 0:
            time.sleep(wait_time)
        self._last_request_at = time.monotonic()
