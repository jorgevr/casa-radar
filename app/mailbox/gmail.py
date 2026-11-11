"""Gmail implementation of MailSource (read-only, GET only).

Contract: specs/001-alert-email-import/contracts/mail-source.md
Only the injected httpx.Client makes requests. Errors carry method, path and status
only, never tokens or message content.
"""
from __future__ import annotations

import base64
import time
from datetime import date
from typing import Callable, Iterator

import httpx

from app.mailbox import AuthRevoked, FolderNotFound, SourceUnavailable, WrongFolder

BASE_URL = "https://gmail.googleapis.com/gmail/v1/"
MIN_INTERVAL_SECONDS = 0.1


class GmailSource:
    def __init__(self, *, client: httpx.Client, access_token: Callable[[], str]) -> None:
        self._client = client
        self._access_token = access_token
        self._last_request: float | None = None

    def _get(self, path: str, params: dict | None = None) -> dict:
        if self._last_request is not None:
            wait = MIN_INTERVAL_SECONDS - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            try:
                response = self._client.get(path, params=params, headers=headers)
            finally:
                self._last_request = time.monotonic()
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"GET {path} failed: {type(exc).__name__}") from None
        status = response.status_code
        if status == 401:
            raise AuthRevoked(f"GET {path} status 401")
        if status != 200:
            raise SourceUnavailable(f"GET {path} status {status}")
        try:
            data = response.json()
        except ValueError:
            raise SourceUnavailable(f"GET {path} status {status} invalid JSON") from None
        if not isinstance(data, dict):
            raise SourceUnavailable(f"GET {path} status {status} unexpected body")
        return data

    def account(self) -> str:
        address = self._get("users/me/profile").get("emailAddress")
        if not isinstance(address, str) or not address:
            raise SourceUnavailable("GET users/me/profile status 200 missing emailAddress")
        return address

    def resolve_folder(self, name: str) -> str:
        for label in self._get("users/me/labels").get("labels") or []:
            if label.get("name") == name and label.get("id"):
                return label["id"]
        raise FolderNotFound(f"folder {name} not found")

    def list_ids(self, folder_id: str, after: date) -> Iterator[str]:
        params = {"labelIds": folder_id, "q": f"after:{after.strftime('%Y/%m/%d')}"}
        while True:
            data = self._get("users/me/messages", params)
            for item in data.get("messages") or []:
                yield item["id"]
            token = data.get("nextPageToken")
            if not token:
                return
            params = {**params, "pageToken": token}

    def fetch_raw(self, folder_id: str, message_id: str) -> bytes:
        path = f"users/me/messages/{message_id}"
        data = self._get(path, {"format": "raw"})
        if folder_id not in (data.get("labelIds") or []):
            raise WrongFolder(f"GET {path} message lacks the folder label")
        raw = data.get("raw")
        if not isinstance(raw, str):
            raise SourceUnavailable(f"GET {path} status 200 missing raw")
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


__all__ = ["GmailSource", "BASE_URL"]
