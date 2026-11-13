"""Mailbox access: the MailSource interface and the only errors the sync loop handles.

Contract: specs/001-alert-email-import/contracts/mail-source.md
Exceptions must carry method, path and status only, never tokens or message content.
"""
from __future__ import annotations

from datetime import date
from typing import Iterator, Protocol, runtime_checkable


class AuthRevoked(Exception):
    """Refresh refused (invalid_grant) or 401 after refresh."""


class FolderNotFound(Exception):
    """The label name does not exist in the mailbox."""


class SourceUnavailable(Exception):
    """Network error, timeout, 5xx or 429."""


class WrongFolder(Exception):
    """The fetched message does not carry the requested folder label."""


@runtime_checkable
class MailSource(Protocol):
    def account(self) -> str:
        """Address shown in the UI."""

    def resolve_folder(self, name: str) -> str:
        """Return the label id; raise FolderNotFound if absent."""

    def list_ids(self, folder_id: str, after: date) -> Iterator[str]:
        """Yield message ids in that folder only, any order."""

    def fetch_raw(self, folder_id: str, message_id: str) -> bytes:
        """Return RFC 822 bytes; raise WrongFolder if the message lacks folder_id."""


__all__ = ["MailSource", "AuthRevoked", "FolderNotFound", "SourceUnavailable", "WrongFolder"]
