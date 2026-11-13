"""Migration 019 (patient safety profile) against a throwaway local database.

Runs real downgrade/upgrade, so it only runs when DATABASE_URL was set on
purpose and points at a local Postgres. It leaves the database at head.
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from tests.conftest import DATABASE_URL_PRESET

_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT / "src/backend/db/migrations/versions/20261113_019_patient_safety_profile.py"
)
_URL = make_url(os.environ["DATABASE_URL"])

pytestmark = pytest.mark.skipif(
    not DATABASE_URL_PRESET or _URL.host not in {"127.0.0.1", "localhost"},
    reason="needs a throwaway local DATABASE_URL (never production)",
)

_STAMP = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
_TOMB_STAMP = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_NEW_TABLES = [
    "profile_entry",
    "recommendation",
    "check_failure",
    "red_flag_escalation",
    "review_item",
]


def _config() -> Config:
    # No ini file: env.py would otherwise reconfigure logging and disable the
    # loggers other tests capture.
    cfg = Config()
    cfg.set_main_option("script_location", str(_ROOT / "src/backend/db/migrations"))
    return cfg


def _load_migration():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("migration_019", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    eng = sa.create_engine(
        _URL.set(drivername="postgresql+psycopg2"), poolclass=sa.pool.NullPool
    )
    yield eng
    command.upgrade(_config(), "head")
    eng.dispose()


@pytest.fixture(scope="module")
def seeded(engine: Engine) -> Iterator[dict[str, str]]:
    """Seed a pre-019 database, upgrade it, and hand back the user ids."""
    command.downgrade(_config(), "018_user_memory_profile")
    ids = {"a": str(uuid.uuid4()), "b": str(uuid.uuid4())}
    with engine.begin() as conn:
        for user_id, conditions, prefs in (
            (
                ids["a"],
                ["diabetes", "ckd"],
                {"vegan": True, "keto": False, "odd": True, "pescetarian": True},
            ),
            (ids["b"], [], {}),
        ):
            conn.execute(
                sa.text(
                    "INSERT INTO user_goal (user_id, conditions, dietary_prefs, "
                    "updated_at) VALUES (:u, :c, CAST(:p AS jsonb), :at)"
                ),
                {"u": user_id, "c": conditions, "p": json.dumps(prefs), "at": _STAMP},
            )
        rows = [
            (ids["a"], "allergic to peanuts", "restriction", None, _STAMP),
            (ids["a"], "avoids red meat", "restriction", None, _STAMP),
            (ids["a"], "avoids nutmeg", "restriction", None, _STAMP),
            (ids["a"], "no shellfish", "restriction", _TOMB_STAMP, _TOMB_STAMP),
            (ids["a"], "likes spicy food", "like", None, _STAMP),
        ]
        for user_id, fact, category, deleted_at, updated_at in rows:
            conn.execute(
                sa.text(
                    "INSERT INTO user_memory (user_id, fact, category, confidence, "
                    "deleted_at, updated_at) VALUES (:u, :f, :c, 1.0, :d, :at)"
                ),
                {
                    "u": user_id,
                    "f": fact,
                    "c": category,
                    "d": deleted_at,
                    "at": updated_at,
                },
            )
    command.upgrade(_config(), "019_patient_safety_profile")
    yield ids
    with engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM user_goal WHERE user_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": list(ids.values())},
        )


def _entries(engine: Engine, user_id: str) -> dict[tuple[str, str], sa.Row]:
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("SELECT * FROM profile_entry WHERE user_id = :u"), {"u": user_id}
        ).all()
    return {(r.entry_type, json.dumps(r.value, sort_keys=True)): r for r in rows}


def _entry_id(engine: Engine, user_id: str, entry_type: str = "diagnosis") -> str:
    with engine.begin() as conn:
        return str(
            conn.execute(
                sa.text(
                    "INSERT INTO profile_entry (user_id, entry_type, value, source, "
                    "state, created_by) VALUES (:u, :t, CAST(:v AS jsonb), 'patient', "
                    "'pending', 'patient') RETURNING id"
                ),
                {"u": user_id, "t": entry_type, "v": json.dumps({"condition": "x"})},
            ).scalar_one()
        )


def test_backfill_copies_conditions_and_diet_chips(
    engine: Engine, seeded: dict[str, str]
) -> None:
    entries = _entries(engine, seeded["a"])

    assert ("diagnosis", '{"condition": "diabetes"}') in entries
    assert ("diagnosis", '{"condition": "ckd"}') in entries
    assert ("diet_setting", '{"setting": "vegan"}') in entries
    # the web's spelling is kept under the chip's name, not dropped
    assert ("diet_setting", '{"setting": "pescatarian"}') in entries
    # false chip and non-chip key are not copied
    assert not any(v for k, v in entries.items() if "keto" in k[1] or "odd" in k[1])
    row = entries[("diagnosis", '{"condition": "ckd"}')]
    assert row.source == "patient"
    assert row.state == "confirmed"
    assert row.created_by == row.confirmed_by == "backfill"
    assert row.created_at == row.confirmed_at == _STAMP
    assert row.label is None
    assert _entries(engine, seeded["b"]) == {}


def test_backfill_splits_allergy_from_exclusion_and_skips_tombstone(
    engine: Engine, seeded: dict[str, str]
) -> None:
    entries = _entries(engine, seeded["a"])

    allergy = entries[("allergy", '{"allergen_group": "peanut"}')]
    assert allergy.label is None
    meat = entries[("food_exclusion", '{"terms": ["avoids red meat"]}')]
    assert meat.label == "avoids red meat"
    # nutmeg is an exclude_term of tree_nut, so it is not an allergy
    assert ("food_exclusion", '{"terms": ["avoids nutmeg"]}') in entries
    assert not any("shellfish" in k[1] for k in entries)
    assert len([k for k in entries if k[0] in {"allergy", "food_exclusion"}]) == 3


def test_backfill_leaves_user_memory_untouched(
    engine: Engine, seeded: dict[str, str]
) -> None:
    with engine.connect() as conn:
        live, tombstones = conn.execute(
            sa.text(
                "SELECT count(*) FILTER (WHERE deleted_at IS NULL AND "
                "category = 'restriction'), count(*) FILTER (WHERE deleted_at "
                "IS NOT NULL) FROM user_memory WHERE user_id = :u"
            ),
            {"u": seeded["a"]},
        ).one()
        mismatched = conn.execute(
            sa.text(
                "SELECT count(*) FROM user_memory "
                "WHERE user_id = :u AND created_at <> updated_at"
            ),
            {"u": seeded["a"]},
        ).scalar_one()
    assert (live, tombstones) == (3, 1)
    # Existing facts take their last-written date as created_at.
    assert mismatched == 0


def test_backfill_is_idempotent(engine: Engine, seeded: dict[str, str]) -> None:
    before = _entries(engine, seeded["a"])
    with engine.begin() as conn:
        _load_migration()._backfill(conn)
    assert _entries(engine, seeded["a"]).keys() == before.keys()


def test_category_check_widened_but_restriction_kept(
    engine: Engine, seeded: dict[str, str]
) -> None:
    with engine.begin() as conn:
        for category in ("cuisine", "budget", "cooking_time", "restriction"):
            conn.execute(
                sa.text(
                    "INSERT INTO user_memory (user_id, fact, category, confidence) "
                    "VALUES (:u, 'x', :c, 1.0)"
                ),
                {"u": seeded["b"], "c": category},
            )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO user_memory (user_id, fact, category, confidence) "
                "VALUES (:u, 'x', 'bogus', 1.0)"
            ),
            {"u": seeded["b"]},
        )


@pytest.mark.parametrize(
    "columns",
    [
        ("entry_type, source, state, created_by", "'bogus', 'patient', 'pending', 'p'"),
        ("entry_type, source, state, created_by", "'allergy', 'bogus', 'pending', 'p'"),
        ("entry_type, source, state, created_by", "'allergy', 'patient', 'bogus', 'p'"),
        # confirmed without confirmed_at
        (
            "entry_type, source, state, created_by",
            "'allergy', 'patient', 'confirmed', 'p'",
        ),
        # retired without retired_at
        (
            "entry_type, source, state, created_by",
            "'allergy', 'patient', 'retired', 'p'",
        ),
        # clinician must be a reviewer
        (
            "entry_type, source, state, created_by",
            "'allergy', 'clinician', 'pending', 'p'",
        ),
    ],
)
def test_profile_entry_check_constraints_reject(
    engine: Engine, seeded: dict[str, str], columns: tuple[str, str]
) -> None:
    cols, vals = columns
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            sa.text(
                f"INSERT INTO profile_entry (user_id, value, {cols}) "
                f"VALUES (:u, '{{}}'::jsonb, {vals})"
            ),
            {"u": seeded["b"]},
        )


def test_clinician_entry_needs_reviewer_actor(
    engine: Engine, seeded: dict[str, str]
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO profile_entry (user_id, entry_type, value, source, "
                "state, created_by) VALUES (:u, 'allergy', '{}'::jsonb, "
                "'clinician', 'pending', :by)"
            ),
            {"u": seeded["b"], "by": f"reviewer:{uuid.uuid4()}"},
        )


def test_client_request_id_unique_per_user(
    engine: Engine, seeded: dict[str, str]
) -> None:
    sql = sa.text(
        "INSERT INTO profile_entry (user_id, entry_type, value, source, state, "
        "created_by, client_request_id) VALUES (:u, 'diagnosis', '{}'::jsonb, "
        "'patient', 'pending', 'patient', 'req-1')"
    )
    with engine.begin() as conn:
        conn.execute(sql, {"u": seeded["b"]})
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(sql, {"u": seeded["b"]})


@pytest.mark.parametrize(
    "assignment",
    [
        "entry_type = 'allergy'",
        'value = \'{"condition": "y"}\'::jsonb',
        "label = 'changed'",
        "source = 'inferred'",
        "created_at = now()",
        "created_by = 'curator'",
        "evidence = 'new words'",
        "replaces_id = gen_random_uuid()",
        "inference_probability = 0.9",
    ],
)
def test_trigger_rejects_changing_immutable_columns(
    engine: Engine, seeded: dict[str, str], assignment: str
) -> None:
    entry = _entry_id(engine, seeded["b"])
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            sa.text(f"UPDATE profile_entry SET {assignment} WHERE id = :i"),
            {"i": entry},
        )


def test_trigger_allows_forward_transitions_only(
    engine: Engine, seeded: dict[str, str]
) -> None:
    entry = _entry_id(engine, seeded["b"])
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE profile_entry SET state = 'confirmed', confirmed_at = now(), "
                "confirmed_by = 'patient' WHERE id = :i"
            ),
            {"i": entry},
        )
    # backward: confirmed -> pending
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE profile_entry SET state = 'pending' WHERE id = :i"),
            {"i": entry},
        )
    # confirmed_at is set once
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE profile_entry SET confirmed_at = now() WHERE id = :i"),
            {"i": entry},
        )
    # non-state columns stay writable
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE profile_entry SET retire_requested_at = now(), "
                "readback_asked_at = now(), conversation_id = 'c1', "
                "mentioned_at = now() WHERE id = :i"
            ),
            {"i": entry},
        )
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE profile_entry SET mentioned_at = now() WHERE id = :i"),
            {"i": entry},
        )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE profile_entry SET state = 'retired', retired_at = now(), "
                "retired_by = 'patient', retired_reason = 'wrong' WHERE id = :i"
            ),
            {"i": entry},
        )


def test_trigger_rejects_any_change_to_a_retired_entry(
    engine: Engine, seeded: dict[str, str]
) -> None:
    entry = _entry_id(engine, seeded["b"])
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE profile_entry SET state = 'retired', retired_at = now() "
                "WHERE id = :i"
            ),
            {"i": entry},
        )
    for assignment in (
        "state = 'confirmed', confirmed_at = now()",
        "readback_asked_at = now()",
    ):
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(
                sa.text(f"UPDATE profile_entry SET {assignment} WHERE id = :i"),
                {"i": entry},
            )


def test_pending_can_be_retired_and_cascade_delete_works(
    engine: Engine,
) -> None:
    user = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO user_goal (user_id) VALUES (:u)"), {"u": user}
        )
    entry = _entry_id(engine, user)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE profile_entry SET state = 'retired', retired_at = now() "
                "WHERE id = :i"
            ),
            {"i": entry},
        )
        conn.execute(
            sa.text(
                "INSERT INTO review_item (user_id, kind, subject_id) "
                "VALUES (:u, 'pending_entry', :s)"
            ),
            {"u": user, "s": entry},
        )
        conn.execute(sa.text("DELETE FROM user_goal WHERE user_id = :u"), {"u": user})
        left = conn.execute(
            sa.text(
                "SELECT (SELECT count(*) FROM profile_entry WHERE user_id = :u) + "
                "(SELECT count(*) FROM review_item WHERE user_id = :u)"
            ),
            {"u": user},
        ).scalar_one()
    assert left == 0


def test_rls_policy_on_every_new_table(engine: Engine, seeded: dict[str, str]) -> None:
    with engine.connect() as conn:
        policies = {
            r.tablename
            for r in conn.execute(
                sa.text(
                    "SELECT tablename FROM pg_policies WHERE policyname LIKE '%_owner'"
                )
            )
        }
        enabled = {
            r.relname
            for r in conn.execute(
                sa.text("SELECT relname FROM pg_class WHERE relrowsecurity")
            )
        }
    assert set(_NEW_TABLES) <= policies
    assert set(_NEW_TABLES) <= enabled


def test_downgrade_is_clean_and_upgrade_reapplies(
    engine: Engine, seeded: dict[str, str]
) -> None:
    command.downgrade(_config(), "018_user_memory_profile")
    inspector = sa.inspect(engine)
    assert not set(_NEW_TABLES) & set(inspector.get_table_names())
    assert "created_at" not in {c["name"] for c in inspector.get_columns("user_memory")}
    with engine.connect() as conn:
        assert not conn.execute(
            sa.text("SELECT 1 FROM pg_proc WHERE proname = 'profile_entry_immutable'")
        ).all()
        # the widened kinds were folded back so the old check holds
        assert not conn.execute(
            sa.text(
                "SELECT 1 FROM user_memory WHERE category IN "
                "('cuisine', 'budget', 'cooking_time')"
            )
        ).all()
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO user_memory (user_id, fact, category, confidence) "
                "VALUES (:u, 'x', 'cuisine', 1.0)"
            ),
            {"u": seeded["b"]},
        )

    command.upgrade(_config(), "019_patient_safety_profile")
    assert ("allergy", '{"allergen_group": "peanut"}') in _entries(engine, seeded["a"])
