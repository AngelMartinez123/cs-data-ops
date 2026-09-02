"""Reusable, credit-safe client for the Data Operations data-service API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_BASE_URL = os.environ.get(
    "DATA_SERVICE_BASE_URL",
    "https://api.example.invalid/v1",
)
RETRYABLE_STATUS_CODES = (429, 502, 503, 504)


class DataServiceError(RuntimeError):
    """A sanitized data-service API error safe to display in logs."""


class CreditCallNotApproved(DataServiceError):
    """Raised when a potentially credit-consuming request was not approved."""


@dataclass(frozen=True)
class RequestStats:
    authentications: int
    api_requests: int


class DataServiceClient:
    """Persistent data-service API client with token refresh and safe retries.

    Search calls are allowed by default. Callers must explicitly construct the
    client with ``allow_credit_calls=True`` and mark a request as
    ``credit_consuming=True`` before a potentially billable endpoint is used.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        allow_credit_calls: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.username = username or os.environ.get("DATA_SERVICE_USER")
        self.password = password or os.environ.get("DATA_SERVICE_PASSWORD")
        if not self.username or not self.password:
            raise DataServiceError(
                "DATA_SERVICE_USER and DATA_SERVICE_PASSWORD are required"
            )

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.allow_credit_calls = allow_credit_calls
        self.session = session or self._build_session()
        self._owns_session = session is None
        self._token: str | None = None
        self._authentications = 0
        self._api_requests = 0

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=4,
            connect=3,
            read=3,
            status=4,
            backoff_factor=0.5,
            status_forcelist=RETRYABLE_STATUS_CODES,
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        session = requests.Session()
        session.headers.update({"Accept": "application/json"})
        session.mount("https://", adapter)
        return session

    @property
    def stats(self) -> RequestStats:
        return RequestStats(self._authentications, self._api_requests)

    def authenticate(self, *, force: bool = False) -> str:
        if self._token and not force:
            return self._token

        try:
            response = self.session.post(
                f"{self.base_url}/authenticate",
                json={"username": self.username, "password": self.password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DataServiceError(
                f"Connect authentication failed: {type(exc).__name__}"
            ) from exc

        self._authentications += 1
        if response.status_code != 200:
            raise DataServiceError(
                f"Connect authentication failed with HTTP {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise DataServiceError(
                "Connect authentication returned invalid JSON"
            ) from exc

        token = payload.get("token") or payload.get("access_token")
        if not token:
            raise DataServiceError(
                "Connect authentication response did not contain a token"
            )
        self._token = str(token)
        return self._token

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        credit_consuming: bool = False,
    ) -> Any:
        if credit_consuming and not self.allow_credit_calls:
            raise CreditCallNotApproved(
                "Potentially credit-consuming Connect request was not approved"
            )

        url = path if path.startswith("https://") else f"{self.base_url}/{path.lstrip('/')}"
        token = self.authenticate()
        response = self._send(method, url, token, params=params, json_body=json_body)

        if response.status_code == 401:
            token = self.authenticate(force=True)
            response = self._send(method, url, token, params=params, json_body=json_body)

        if not response.ok:
            message = self._safe_error_message(response)
            raise DataServiceError(
                f"data-service API request failed with HTTP {response.status_code}: {message}"
            )

        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise DataServiceError("data-service API returned invalid JSON") from exc

    def _send(
        self,
        method: str,
        url: str,
        token: str,
        *,
        params: Mapping[str, Any] | None,
        json_body: Any,
    ) -> requests.Response:
        self._api_requests += 1
        try:
            return self.session.request(
                method.upper(),
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DataServiceError(
                f"data-service API request failed: {type(exc).__name__}"
            ) from exc

    @staticmethod
    def _safe_error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.reason or "request rejected"
        if isinstance(payload, dict):
            value = payload.get("message") or payload.get("error")
            if isinstance(value, str):
                return value[:300]
        return "request rejected"

    def search_companies(self, **params: Any) -> Any:
        """Search companies without opting into report-credit endpoints."""
        return self.request_json("GET", "/companies", params=params)

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "DataServiceClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
