"""FR-024: the alert fixtures in the repository are anonymised."""
import importlib.util
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _anonymiser():
    spec = importlib.util.spec_from_file_location("anonymise_eml", FIXTURES / "anonymise_eml.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fixtures_pass_the_anonymiser_check():
    assert _anonymiser().check(FIXTURES / "emails") is True


def test_at_least_twelve_fixtures():
    assert len(list((FIXTURES / "emails").glob("*.eml"))) >= 12
