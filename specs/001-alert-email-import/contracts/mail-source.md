# Contract: Mail source (mailbox access)

Internal interface between the sync loop (`app/alerts_sync.py`) and the provider client
(`app/mailbox/gmail.py`). Tests use a fake implementation serving fixture files; no test ever
reaches Google (Article VI). Background: [research R1–R8](../research.md#r1-how-the-tool-reads-the-mailbox).

## Interface

```text
MailSource
  account() -> str                                   # address shown in the UI
  resolve_folder(name: str) -> str                   # label id; FolderNotFound if absent
  list_ids(folder_id: str, after: date) -> Iterator[str]   # ids in that folder only, any order
  fetch_raw(folder_id: str, message_id: str) -> bytes      # RFC 822 bytes; WrongFolder if the
                                                     # message does not carry folder_id
```

Errors (the only ones the sync loop handles):

| Error | Meaning | Sync loop reaction |
|---|---|---|
| `AuthRevoked` | refresh refused (`invalid_grant`) or 401 after refresh | stop; `auth_state = revoked`; pause auto sync (FR-029) |
| `FolderNotFound` | label name not found | stop; error "folder <name> not found"; no fallback |
| `SourceUnavailable` | network error, timeout, 5xx, 429 | stop; error recorded; next scheduled run retries |
| `WrongFolder` | fetched message lacks the label | discard without storing; stop with internal error (FR-016) |

## Gmail implementation rules

- Scope requested: `https://www.googleapis.com/auth/gmail.readonly` only. Requesting any other
  scope is a test failure.
- Calls allowed: `GET users/me/profile`, `GET users/me/labels` (setup and label re-resolution only),
  `GET users/me/messages?labelIds=<id>&q=after:<yyyy/mm/dd>&pageToken=…`,
  `GET users/me/messages/<id>?format=raw`. No other method; no POST/PUT/PATCH/DELETE to Gmail.
  A test asserts the method and path of every request the client makes.
- Sequential requests, ≥ 100 ms apart (R7). No retries inside a sync.
- Secrets: the access token lives in memory only; the refresh token is read from and written to the
  app folder (R4). Exceptions carry method, path and status only.

## Authorisation flow (setup and re-authorise)

1. User places `client_secret.json` in `%LOCALAPPDATA%\casa-radar\` (the UI shows the path).
2. `authorize()` starts a loopback listener on `127.0.0.1:<random port>`, opens the browser at the
   consent URL (scope above, PKCE S256, `access_type=offline`, `prompt=consent`), waits up to
   5 minutes for the redirect, exchanges the code, stores the refresh token encrypted.
3. `account()` is read and shown; the user types or picks the label name; `resolve_folder()` stores
   the id. Setup screen text states: "Google's read-only permission lets this app read all your mail;
   Casa Radar only reads the label you choose and cannot change anything. Revoke it at any time at
   myaccount.google.com/permissions."
4. "Disconnect" deletes the token file and sets `auth_state = not_configured`; revocation itself is
   done by the user at Google (the tool makes no revoke call to avoid sending anything extra).
