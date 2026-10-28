"""Shared fixtures. Every test runs against temporary paths and, where asked, without network."""
import shutil
import socket
from pathlib import Path

import pytest

from app import db
from app.etl import indicators as ind_etl

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_NEEDS = ROOT / "config" / "needs.example.yaml"
EMAILS = Path(__file__).parent / "fixtures" / "emails"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: timing tests, excluded from the per-task gate")


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    """Keep every test away from data/, config/needs.yaml and the real app folder (CASA_APPDATA)."""
    needs = tmp_path / "needs.yaml"
    shutil.copyfile(EXAMPLE_NEEDS, needs)
    paths = {"CASA_DB": tmp_path / "casa.db", "CASA_NEEDS": needs, "CASA_APPDATA": tmp_path / "appdata"}
    for key, value in paths.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setattr(db, "DB_PATH", str(paths["CASA_DB"]))
    monkeypatch.setattr(db, "NEEDS_PATH", str(needs))
    return paths


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    ind_etl.seed_madrid_districts(c)
    return c


@pytest.fixture
def needs():
    return db.load_needs(str(EXAMPLE_NEEDS))


@pytest.fixture
def fixture_emails():
    return sorted(EMAILS.glob("*.eml"))


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access in test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
