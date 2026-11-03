"""T035 fix loop 1: the origin LABEL of a user-entered new_build (reviews/T035-r1.md finding 1).

Invariant (data-model `field_sources`, FR-023, reviews/T026-r5.md): a user-owned value is never labelled 'alert';
a value entered through PATCH is labelled 'manual' (a USER_ORIGINS value, the same label POST /api/listings and the
price/area/bedrooms edits use). Clearing with null drops the user label and the derivation then labels honestly:
an email-stated new-build comes back as (1, 'email') labelled 'alert'; nothing stated -> NULL with no 'new_build' key.

Data: the anonymised fixtures through POST /api/alerts/import. Listing idealista:112882173 is the obra-nueva email
(states new-build: new_build 1, origin 'email', label 'alert'). The chalet 112842548 (bajada-de-precio email) has no
new-build statement. Expected values are written by hand.
"""
import json

import pytest

from app import derive
from app.categories import recategorise_all

from .test_categories_api import (_chalet, _db, _new_build, _patch, client, db_path, imported,  # noqa: F401
                                  no_aliases, rules_path)

STATED = "idealista:112882173"  # obra-nueva fixture: the email states new-build


def _sources(db_path, lid):
    with _db(db_path) as c:
        r = c.execute("SELECT field_sources FROM listings WHERE id=?", (lid,)).fetchone()
        return json.loads(r["field_sources"])


def _others(sources):
    return {k: v for k, v in sources.items() if k != "new_build"}


def test_setup_stated_listing_is_email_labelled_alert(imported, db_path):
    assert _new_build(db_path, STATED) == (1, "email")
    assert _sources(db_path, STATED)["new_build"] == "alert"


# (1) prior email statement
@pytest.mark.parametrize("value, stored", [(False, 0), (True, 1)])
def test_patch_over_email_statement_labels_manual(imported, db_path, value, stored):
    assert _patch(imported, STATED, {"new_build": value}).status_code == 200
    assert _new_build(db_path, STATED) == (stored, "user")
    assert _sources(db_path, STATED)["new_build"] == "manual"   # not 'alert'


# (2) no prior value
def test_patch_true_without_prior_value_labels_manual(imported, db_path):
    lid = _chalet(db_path)
    assert "new_build" not in _sources(db_path, lid)  # setup: nothing imputed
    assert _patch(imported, lid, {"new_build": True}).status_code == 200
    assert _new_build(db_path, lid) == (1, "user")
    assert _sources(db_path, lid)["new_build"] == "manual"


def test_patch_false_without_prior_value_labels_manual(imported, db_path):
    lid = _chalet(db_path)
    assert _patch(imported, lid, {"new_build": False}).status_code == 200
    assert _new_build(db_path, lid) == (0, "user")
    assert _sources(db_path, lid)["new_build"] == "manual"


# (3) clearing
def test_clear_over_email_statement_relabels_alert(imported, db_path):
    assert _patch(imported, STATED, {"new_build": False}).status_code == 200
    assert _patch(imported, STATED, {"new_build": None}).status_code == 200
    assert _new_build(db_path, STATED) == (1, "email")
    assert _sources(db_path, STATED)["new_build"] == "alert"


def test_clear_without_statement_drops_label(imported, db_path):
    lid = _chalet(db_path)
    assert _patch(imported, lid, {"new_build": True}).status_code == 200
    assert _patch(imported, lid, {"new_build": None}).status_code == 200
    assert _new_build(db_path, lid) == (None, None)
    assert "new_build" not in _sources(db_path, lid)


# (4) order independence
@pytest.mark.parametrize("lid_kind", ["stated", "chalet"])
def test_user_label_survives_rederivation(imported, db_path, lid_kind):
    lid = STATED if lid_kind == "stated" else _chalet(db_path)
    assert _patch(imported, lid, {"new_build": False}).status_code == 200
    with _db(db_path) as c:
        derive.derive_listing(c, lid)
        c.commit()
    assert _new_build(db_path, lid) == (0, "user")
    assert _sources(db_path, lid)["new_build"] == "manual"
    with _db(db_path) as c:
        recategorise_all(c)
    assert _new_build(db_path, lid) == (0, "user")
    assert _sources(db_path, lid)["new_build"] == "manual"


# (5) nothing else in field_sources changes
@pytest.mark.parametrize("body", [{"new_build": True}, {"new_build": False}, {"new_build": None}])
def test_patch_leaves_other_field_sources_unchanged(imported, db_path, body):
    for lid in (STATED, _chalet(db_path)):
        before = _others(_sources(db_path, lid))
        assert _patch(imported, lid, body).status_code == 200
        assert _others(_sources(db_path, lid)) == before
