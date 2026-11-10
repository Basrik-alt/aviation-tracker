"""Клиенты внешних API."""

from aviation.api.http_client import ApiError, HttpClient
from aviation.api.nominatim_client import NominatimClient
from aviation.api.opensky_client import OpenSkyClient

__all__ = ["ApiError", "HttpClient", "NominatimClient", "OpenSkyClient"]
