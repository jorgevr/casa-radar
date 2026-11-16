"""Repository must not contain OAuth secrets or refresh-token strings (T063)."""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Forbidden credential file names (Article III / T063).
FORBIDDEN_NAME_PATTERNS = ("client_secret*.json", "token*.json")
FORBIDDEN_EXACT_NAMES = {"token.bin"}

# Build artefacts are gitignored, not repository content.
SKIP_DIR_NAMES = {".git", "__pycache__", ".pytest_cache", ".venv", "venv"}
SKIP_FILE_SUFFIXES = (".pyc",)

# Real Google refresh tokens carry 45+ random body characters; the repository's
# existing fake test tokens use <= 34 obviously fake body characters, so this
# length gate flags realistic tokens without matching those fakes. Trade-off:
# a real token whose body is shorter than this threshold would be missed.
MIN_TOKEN_BODY = 40

# Household data files must never be read by this scan.
SKIP_CONTENT_PATHS = (
    Path("config/needs.yaml"),
    Path("config/zone_aliases.yaml"),
)
SKIP_CONTENT_DIRS = (Path("data"),)


def _token_re() -> re.Pattern[str]:
    # Built at runtime so this source file never contains a literal token-shaped string.
    return re.compile(
        "".join(["1", "/", "/", "0"]) + r"[A-Za-z0-9_\-]{" + str(MIN_TOKEN_BODY) + r",}"
    )


def _is_forbidden_name(name: str) -> bool:
    if name in FORBIDDEN_EXACT_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in FORBIDDEN_NAME_PATTERNS)


def _is_skipped_file(name: str) -> bool:
    return name.endswith(SKIP_FILE_SUFFIXES)


def _should_skip_content(rel: Path) -> bool:
    for d in SKIP_CONTENT_DIRS:
        if rel == d or d in rel.parents:
            return True
    return rel in SKIP_CONTENT_PATHS


def find_forbidden_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            if _is_skipped_file(name):
                continue
            if _is_forbidden_name(name):
                found.append(base / name)
    return sorted(found)


def find_refresh_token_strings(root: Path) -> list[Path]:
    pat = _token_re()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            if _is_skipped_file(name):
                continue
            path = base / name
            rel = path.relative_to(root)
            if _is_forbidden_name(name) or _should_skip_content(rel):
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("utf-8", errors="ignore")
            if pat.search(text):
                found.append(path)
    return sorted(found)


def _assert_no_secrets(root: Path) -> None:
    bad_files = find_forbidden_files(root)
    assert not bad_files, "forbidden secret file(s): " + ", ".join(
        str(p.relative_to(root)) for p in bad_files
    )
    bad_tokens = find_refresh_token_strings(root)
    assert not bad_tokens, "refresh-token-shaped string(s) in: " + ", ".join(
        str(p.relative_to(root)) for p in bad_tokens
    )


def test_repo_has_no_forbidden_secret_files(no_network):
    assert find_forbidden_files(ROOT) == []


def test_repo_has_no_refresh_token_strings(no_network):
    assert find_refresh_token_strings(ROOT) == []


def test_detects_forbidden_file_names(tmp_path, no_network):
    (tmp_path / "client_secret_desktop.json").write_text("{}", encoding="utf-8")
    (tmp_path / "token.json").write_text("{}", encoding="utf-8")
    (tmp_path / "token.bin").write_bytes(b"x")
    found = {p.name for p in find_forbidden_files(tmp_path)}
    assert found == {"client_secret_desktop.json", "token.json", "token.bin"}


def test_detects_refresh_token_shaped_string(tmp_path, no_network):
    sample = "".join(["1", "/", "/", "0"]) + "a" * MIN_TOKEN_BODY
    target = tmp_path / "notes.txt"
    target.write_text("prefix " + sample + " suffix", encoding="utf-8")
    found = find_refresh_token_strings(tmp_path)
    assert found == [target]
    # The failure message must report only the path, never the matched content.
    try:
        _assert_no_secrets(tmp_path)
    except AssertionError as exc:
        msg = str(exc)
        assert str(target.relative_to(tmp_path)) in msg
        assert sample not in msg
    else:
        raise AssertionError("expected a refresh-token-shaped string to be detected")


def test_short_obviously_fake_token_tolerated(tmp_path, no_network):
    # Trade-off: the length gate (MIN_TOKEN_BODY) tolerates short, obviously fake
    # tokens used by existing repository tests/handoffs (<= 34 body chars) at the
    # cost of missing a hypothetical real token with an unusually short body. We
    # only flag realistic-length tokens and never inspect or report token content.
    fake_body = "".join(["fake", "-", "refresh", "-", "token", "-", "FOR", "-", "TESTS", "-", "ONLY"])
    short_fake = "".join(["1", "/", "/", "0"]) + fake_body
    assert len(fake_body) < MIN_TOKEN_BODY
    target = tmp_path / "fake.txt"
    target.write_text(short_fake, encoding="utf-8")
    assert find_refresh_token_strings(tmp_path) == []
