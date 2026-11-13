"""The hard profile: values, labels, state transitions, rendering, limits."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.safety import profile
from backend.safety.matching import allergen_group_for, restriction_value
from backend.safety.profile import (
    AllergyValue,
    DiagnosisValue,
    DietSettingValue,
    FoodExclusionValue,
    MedicationValue,
    NutrientLimitValue,
    PhysicalLimitationValue,
)
from backend.safety.tables import load_tables
from tests.profile_helpers import hard_entry

TABLES = load_tables()
PEANUT = AllergyValue(allergen_group="peanut")


def _sodium(amount: float = 1500, **extra) -> NutrientLimitValue:
    return NutrientLimitValue(
        nutrient="sodium", amount=amount, unit="mg", period="per_day", **extra
    )


async def _add(user_id: str, value, state: str = "confirmed", **kwargs):
    return await profile.add_entry(
        user_id,
        value,
        source="patient",
        state=state,
        created_by="patient",
        **kwargs,
    )


# --- values and labels (no database) -----------------------------------------


def test_values_reject_unknown_fields_and_bad_shapes() -> None:
    with pytest.raises(ValidationError):
        DiagnosisValue(condition="ckd", note="x")
    with pytest.raises(ValidationError):
        AllergyValue()
    with pytest.raises(ValidationError):
        AllergyValue(allergen_group="peanut", custom_terms=["kiwi"])
    with pytest.raises(ValidationError):
        DietSettingValue(setting="carnivore")
    with pytest.raises(ValidationError):
        FoodExclusionValue(terms=[])
    with pytest.raises(ValidationError):
        FoodExclusionValue(terms=[f"t{i}" for i in range(11)])
    with pytest.raises(ValidationError):
        _sodium(amount=0)
    with pytest.raises(ValidationError):
        _sodium(amount=50, min_amount=60)
    with pytest.raises(ValidationError):
        NutrientLimitValue(nutrient="iron", amount=1, unit="mg", period="per_day")
    with pytest.raises(ValidationError):
        PhysicalLimitationValue(kind="chewing", max_active_minutes=0)


def test_parse_value_wraps_errors_and_unknown_types() -> None:
    assert profile.parse_value("allergy", {"allergen_group": "peanut"}) == PEANUT
    with pytest.raises(ValueError, match="unknown entry type"):
        profile.parse_value("mood", {})
    with pytest.raises(ValueError):
        profile.parse_value("allergy", {})


@pytest.mark.parametrize(
    ("value", "label"),
    [
        (PEANUT, "Peanut allergy"),
        (AllergyValue(custom_terms=["kiwi", "mango"]), "Allergy: kiwi, mango"),
        (DiagnosisValue(condition="ckd"), "Chronic kidney disease"),
        (DiagnosisValue(condition="gout"), "Gout"),
        (MedicationValue(name="Warfarin 5mg"), "Warfarin 5mg"),
        (PhysicalLimitationValue(kind="swallowing"), "Difficulty swallowing"),
        (
            PhysicalLimitationValue(kind="chewing", max_texture="soft_bite_sized"),
            "Difficulty chewing: up to soft bite sized textures",
        ),
        (
            PhysicalLimitationValue(kind="standing_time", max_active_minutes=15),
            "Limited standing time: up to 15 minutes on your feet",
        ),
        (_sodium(), "Sodium: up to 1,500 mg a day"),
        (
            NutrientLimitValue(
                nutrient="protein",
                amount=60,
                min_amount=50,
                unit="g",
                period="per_day",
            ),
            "Protein: 50-60 g a day",
        ),
        (
            NutrientLimitValue(
                nutrient="potassium", amount=800.5, unit="mg", period="per_meal"
            ),
            "Potassium: up to 800.5 mg a meal",
        ),
        (DietSettingValue(setting="gluten_free"), "Gluten free"),
        (FoodExclusionValue(terms=["pork", "beef"]), "No pork, beef"),
    ],
)
def test_labels_are_derived_from_typed_values(value, label) -> None:
    assert profile.label_for(hard_entry(value), TABLES) == label


def test_label_is_stored_only_for_free_text_values() -> None:
    assert profile._keep_label(FoodExclusionValue(terms=["pork"]), "No pork") == (
        "No pork"
    )
    assert profile._keep_label(AllergyValue(custom_terms=["kiwi"]), "Kiwi") == "Kiwi"
    assert profile._keep_label(PEANUT, "Anything") is None
    assert profile._keep_label(_sodium(), "Anything") is None


def test_limit_text_ranges_and_ceilings() -> None:
    assert profile.limit_text(_sodium()) == "up to 1,500 mg a day"
    assert profile.limit_text(_sodium(amount=1500, min_amount=1000)) == (
        "1,000-1,500 mg a day"
    )


# --- rendering ---------------------------------------------------------------


def test_render_block_lists_confirmed_in_full_and_pending_apart() -> None:
    entries = [
        hard_entry(PEANUT),
        hard_entry(FoodExclusionValue(terms=["pork"])),
        hard_entry(DietSettingValue(setting="vegetarian")),
        hard_entry(DiagnosisValue(condition="ckd")),
        hard_entry(MedicationValue(name="warfarin")),
        hard_entry(PhysicalLimitationValue(kind="grip")),
        hard_entry(_sodium()),
        hard_entry(AllergyValue(allergen_group="milk"), "pending"),
    ]

    block = profile.render_block(entries, TABLES)

    assert "Allergies (never serve, including derived ingredients): Peanut allergy" in (
        block
    )
    assert "Never suggest (hard restrictions): No pork" in block
    assert "Diet settings (binding): vegetarian" in block
    assert "Declared health conditions: chronic kidney disease." in block
    assert "Medications: warfarin" in block
    assert "Physical limitations: Limited grip strength" in block
    assert "Nutrient limits: Sodium: up to 1,500 mg a day" in block
    # A pending entry never appears among the binding lines.
    assert block.count("Milk allergy") == 1
    assert block.splitlines()[-1] == (
        "- Awaiting confirmation, do not apply until the patient confirms: Milk allergy"
    )


def test_render_block_is_empty_for_an_empty_profile() -> None:
    assert profile.render_block([], TABLES) == ""


def test_render_block_raises_instead_of_truncating() -> None:
    tunables = MagicMock()
    tunables.safety.hard_profile_max_entries = 2
    entries = [hard_entry(FoodExclusionValue(terms=[f"f{i}"])) for i in range(3)]

    with patch("backend.safety.profile.get_tunables", return_value=tunables):
        with pytest.raises(profile.ProfileTooLarge):
            profile.render_block(entries, TABLES)
        # Pending entries do not count towards what binds.
        pending = [hard_entry(e.value, "pending") for e in entries]
        assert "Awaiting confirmation" in profile.render_block(pending, TABLES)


def test_missing_values_names_the_limits_a_condition_expects() -> None:
    entries = [
        hard_entry(DiagnosisValue(condition="ckd")),
        hard_entry(
            NutrientLimitValue(
                nutrient="potassium", amount=2000, unit="mg", period="per_day"
            )
        ),
        hard_entry(DiagnosisValue(condition="gout")),
    ]

    assert profile.missing_values(entries, TABLES) == [
        "phosphorus limit for chronic kidney disease",
        "protein limit for chronic kidney disease",
        "sodium limit for chronic kidney disease",
        "fluid limit for chronic kidney disease",
    ]


def test_version_ignores_pending_and_changes_with_the_confirmed_set() -> None:
    first = hard_entry(PEANUT)
    second = hard_entry(DietSettingValue(setting="vegan"))
    pending = hard_entry(FoodExclusionValue(terms=["pork"]), "pending")

    version = profile.version_of([first])

    assert profile.version_of([first, pending]) == version
    assert profile.version_of([first, second]) != version
    assert profile.version_of([second, first]) == profile.version_of([first, second])
    assert profile.version_of([]) != version


# --- the matcher -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "group"),
    [
        ("Allergic to peanuts", "peanut"),
        ("reacts to peanut oil", "peanut"),
        ("can't have whey", "milk"),
        ("allergic to almond milk", "tree_nut"),
        ("no nutmeg", None),
        ("avoids pork", None),
    ],
)
def test_allergen_group_for(text, group) -> None:
    assert allergen_group_for(text, TABLES) == group


def test_restriction_value_types_allergies_and_exclusions() -> None:
    assert restriction_value("Allergic to peanuts", TABLES) == (PEANUT, None)
    assert restriction_value("No pork", TABLES) == (
        FoodExclusionValue(terms=["No pork"]),
        "No pork",
    )


# --- state transitions (local Postgres) --------------------------------------


async def test_pending_entries_do_not_bind_until_confirmed(db_user) -> None:
    entry = await _add(db_user, PEANUT, "pending")

    live = await profile.load_hard_profile(db_user)
    assert [e.state for e in live] == ["pending"]
    assert profile.confirmed(live) == []
    assert "Allergies" not in profile.render_block(live, TABLES)

    confirmed = await profile.confirm(db_user, entry.id)

    assert confirmed.state == "confirmed" and confirmed.confirmed_by == "patient"
    assert [
        e.id for e in profile.confirmed(await profile.load_hard_profile(db_user))
    ] == [entry.id]


async def test_patient_entries_are_confirmed_on_creation(db_user) -> None:
    entry = await _add(db_user, PEANUT)

    assert entry.state == "confirmed" and entry.confirmed_at is not None
    assert (entry.source, entry.created_by) == ("patient", "patient")


async def test_edit_retires_the_old_entry_and_links_the_new_one(db_user) -> None:
    old = await _add(db_user, _sodium(1500))

    new = await profile.replace(db_user, old.id, _sodium(1200), client_request_id="r1")

    assert new.replaces_id == old.id and new.state == "confirmed"
    live = await profile.load_hard_profile(db_user)
    assert [e.id for e in live] == [new.id]
    history = {e.id: e for e in await profile.load_history(db_user)}
    assert history[old.id].state == "retired"
    assert history[old.id].retired_reason == "replaced"
    # The old value is intact: an edit never rewrites a row.
    assert history[old.id].value == _sodium(1500)
    # Repeating the request returns the first result and adds nothing.
    again = await profile.replace(
        db_user, old.id, _sodium(1200), client_request_id="r1"
    )
    assert again.id == new.id
    assert len(await profile.load_history(db_user)) == 2


async def test_replace_records_who_made_and_confirmed_the_new_entry(db_user) -> None:
    old = await _add(db_user, _sodium(1500))

    new = await profile.replace(
        db_user,
        old.id,
        _sodium(1200),
        created_by="reviewer:r1",
        source="clinician",
        confirmed_by="reviewer:r1",
    )

    assert (new.source, new.created_by, new.confirmed_by) == (
        "clinician",
        "reviewer:r1",
        "reviewer:r1",
    )
    history = {e.id: e for e in await profile.load_history(db_user)}
    assert history[old.id].retired_by == "reviewer:r1"


async def test_replace_needs_a_confirmed_entry_of_the_same_type(db_user) -> None:
    pending = await _add(db_user, PEANUT, "pending")
    confirmed = await _add(db_user, _sodium())

    with pytest.raises(profile.StateConflict):
        await profile.replace(db_user, pending.id, PEANUT)
    with pytest.raises(profile.StateConflict):
        await profile.replace(db_user, confirmed.id, PEANUT)


async def test_confirm_deny_retire_are_idempotent_and_conflicts_are_explicit(
    db_user,
) -> None:
    pending = await _add(db_user, PEANUT, "pending")
    first = await profile.confirm(db_user, pending.id)
    second = await profile.confirm(db_user, pending.id)
    assert second.confirmed_at == first.confirmed_at

    with pytest.raises(profile.StateConflict):
        await profile.deny(db_user, pending.id)

    retired = await profile.retire(db_user, pending.id)
    assert retired.state == "retired" and retired.retired_by == "patient"
    assert (await profile.retire(db_user, pending.id)).retired_at == retired.retired_at
    with pytest.raises(profile.StateConflict):
        await profile.confirm(db_user, pending.id)

    unwanted = await _add(db_user, DietSettingValue(setting="keto"), "pending")
    denied = await profile.deny(db_user, unwanted.id)
    assert denied.retired_reason == "denied"
    assert (await profile.deny(db_user, unwanted.id)).retired_at == denied.retired_at
    with pytest.raises(profile.StateConflict):
        await profile.retire(db_user, (await _add(db_user, PEANUT, "pending")).id)
    with pytest.raises(profile.StateConflict):
        await profile.request_retirement(db_user, unwanted.id)


async def test_a_retirement_request_keeps_the_entry_binding(db_user) -> None:
    entry = await _add(db_user, PEANUT)

    requested = await profile.request_retirement(db_user, entry.id)

    assert requested.state == "confirmed" and requested.retire_requested_at
    assert len(profile.confirmed(await profile.load_hard_profile(db_user))) == 1
    await profile.retire(db_user, entry.id)
    assert await profile.load_hard_profile(db_user) == []


async def test_an_inferred_entry_keeps_its_evidence_probability_and_confirmer(
    db_user,
) -> None:
    entry = await profile.add_entry(
        db_user,
        PEANUT,
        source="inferred",
        state="confirmed",
        created_by="curator",
        confirmed_by="inference",
        evidence="I'm allergic to peanuts",
        inference_probability=0.97,
    )

    (loaded,) = await profile.load_hard_profile(db_user)

    assert loaded.id == entry.id
    assert (loaded.confirmed_by, loaded.created_by) == ("inference", "curator")
    assert loaded.evidence == "I'm allergic to peanuts"
    assert loaded.inference_probability == pytest.approx(0.97, abs=1e-3)
    assert loaded.mentioned_at is None and loaded.readback_asked_at is None


async def test_a_retirement_request_can_be_withdrawn_and_asked_again(db_user) -> None:
    entry = await _add(db_user, PEANUT)
    await profile.request_retirement(db_user, entry.id)

    withdrawn = await profile.cancel_retirement(db_user, entry.id)
    again = await profile.request_retirement(db_user, entry.id)

    assert withdrawn.retire_requested_at is None and withdrawn.state == "confirmed"
    assert again.retire_requested_at is not None
    pending = await _add(db_user, DietSettingValue(setting="vegan"), "pending")
    with pytest.raises(profile.StateConflict):
        await profile.cancel_retirement(db_user, pending.id)


async def test_readback_is_recorded_per_batch_and_can_be_asked_again(db_user) -> None:
    first = await _add(db_user, PEANUT, "pending")
    second = await _add(db_user, DietSettingValue(setting="vegan"), "pending")

    asked = await profile.mark_readback(db_user, [first.id, second.id], "conv-1")
    again = await profile.mark_readback(db_user, [first.id], "conv-2")

    entries = {e.id: e for e in await profile.load_hard_profile(db_user)}
    assert entries[second.id].readback_asked_at == asked
    assert entries[second.id].conversation_id == "conv-1"
    assert entries[first.id].readback_asked_at == again
    assert entries[first.id].conversation_id == "conv-2"


async def test_an_inferred_entry_is_mentioned_once(db_user) -> None:
    entry = await profile.add_entry(
        db_user,
        PEANUT,
        source="inferred",
        state="confirmed",
        created_by="curator",
        confirmed_by="inference",
    )

    first = await profile.mark_mentioned(db_user, entry.id)
    second = await profile.mark_mentioned(db_user, entry.id)

    assert first.mentioned_at is not None
    assert second.mentioned_at == first.mentioned_at


async def test_confirming_a_replacement_retires_the_confirmed_entry_it_replaces(
    db_user,
) -> None:
    old = await _add(db_user, _sodium(1500))
    pending = await profile.add_entry(
        db_user,
        _sodium(2300),
        source="inferred",
        state="pending",
        created_by="curator",
        replaces_id=old.id,
    )

    # Until confirmed the stricter limit keeps binding and nothing else does.
    live = await profile.load_hard_profile(db_user)
    assert [e.id for e in profile.confirmed(live)] == [old.id]

    await profile.confirm(db_user, pending.id)

    history = {e.id: e for e in await profile.load_history(db_user)}
    assert history[old.id].state == "retired"
    assert history[old.id].retired_reason == "replaced"
    assert history[pending.id].state == "confirmed"
    assert [e.id for e in await profile.load_hard_profile(db_user)] == [pending.id]


async def test_denying_a_replacement_leaves_the_confirmed_entry(db_user) -> None:
    old = await _add(db_user, _sodium(1500))
    pending = await profile.add_entry(
        db_user,
        _sodium(2300),
        source="inferred",
        state="pending",
        created_by="curator",
        replaces_id=old.id,
    )

    await profile.deny(db_user, pending.id)

    assert [e.id for e in await profile.load_hard_profile(db_user)] == [old.id]


async def test_confirming_a_replacement_whose_target_already_retired_still_works(
    db_user,
) -> None:
    old = await _add(db_user, _sodium(1500))
    pending = await profile.add_entry(
        db_user,
        _sodium(2300),
        source="inferred",
        state="pending",
        created_by="curator",
        replaces_id=old.id,
    )
    await profile.retire(db_user, old.id)

    confirmed = await profile.confirm(db_user, pending.id)

    assert confirmed.state == "confirmed"


async def test_version_changes_when_an_entry_is_confirmed_or_retired(db_user) -> None:
    pending = await _add(db_user, PEANUT, "pending")
    v0 = profile.version_of(await profile.load_hard_profile(db_user))
    await profile.confirm(db_user, pending.id)
    v1 = profile.version_of(await profile.load_hard_profile(db_user))
    await profile.retire(db_user, pending.id)
    v2 = profile.version_of(await profile.load_hard_profile(db_user))

    # A pending entry does not bind, so it does not move the version.
    assert v1 not in {v0, v2}
    assert v2 == v0


async def test_other_users_entries_are_not_found(db_user) -> None:
    entry = await _add(db_user, PEANUT)

    with pytest.raises(profile.EntryNotFound):
        await profile.confirm("00000000-0000-4000-8000-000000000000", entry.id)
    with pytest.raises(profile.EntryNotFound):
        await profile.get_entry(db_user, "not-a-uuid")


async def test_the_live_cap_is_enforced_and_retired_entries_free_room(db_user) -> None:
    tunables = MagicMock()
    tunables.safety.hard_profile_max_entries = 2
    with patch("backend.safety.profile.get_tunables", return_value=tunables):
        first = await _add(db_user, FoodExclusionValue(terms=["a"]))
        await _add(db_user, FoodExclusionValue(terms=["b"]), "pending")
        with pytest.raises(profile.ProfileFull):
            await _add(db_user, FoodExclusionValue(terms=["c"]))
        # An edit is net zero, so it works at the cap.
        edited = await profile.replace(
            db_user, first.id, FoodExclusionValue(terms=["a2"])
        )
        await profile.retire(db_user, edited.id)
        await _add(db_user, FoodExclusionValue(terms=["c"]))


async def test_client_request_id_makes_creation_idempotent(db_user) -> None:
    one = await _add(db_user, PEANUT, client_request_id="req-1")
    two = await _add(db_user, PEANUT, client_request_id="req-1")

    assert one.id == two.id
    assert len(await profile.load_history(db_user)) == 1


async def test_set_declarations_diffs_settings_choices(db_user) -> None:
    managed = {"diabetes", "ckd", "hypertension", "prediabetes"}
    gout = await _add(db_user, DiagnosisValue(condition="gout"))
    pending_vegan = await _add(db_user, DietSettingValue(setting="vegan"), "pending")

    await profile.set_declarations(
        db_user,
        conditions=["ckd", "diabetes"],
        managed_conditions=managed,
        diet_settings=["vegan", "keto"],
    )
    live = await profile.load_hard_profile(db_user)

    assert profile.declared_conditions(live) == ["gout", "ckd", "diabetes"] or (
        sorted(profile.declared_conditions(live)) == ["ckd", "diabetes", "gout"]
    )
    assert profile.active_diet_settings(live) == ["keto", "vegan"]
    # The pending entry was confirmed in place, not duplicated.
    assert any(e.id == pending_vegan.id and e.state == "confirmed" for e in live)
    assert any(e.id == gout.id for e in live)

    # None leaves conditions alone; a smaller list retires; unmanaged stay.
    await profile.set_declarations(
        db_user, conditions=None, managed_conditions=managed, diet_settings=["keto"]
    )
    live = await profile.load_hard_profile(db_user)
    assert profile.active_diet_settings(live) == ["keto"]
    assert "ckd" in profile.declared_conditions(live)
    await profile.set_declarations(
        db_user, conditions=["ckd"], managed_conditions=managed, diet_settings=["keto"]
    )
    live = await profile.load_hard_profile(db_user)
    assert sorted(profile.declared_conditions(live)) == ["ckd", "gout"]
    history = {e.id: e for e in await profile.load_history(db_user)}
    assert history[pending_vegan.id].retired_reason == "removed_in_settings"


async def test_set_declarations_keeps_the_order_the_patient_chose(db_user) -> None:
    managed = {"diabetes", "ckd"}
    await profile.set_declarations(
        db_user,
        conditions=["diabetes", "ckd"],
        managed_conditions=managed,
        diet_settings=[],
    )

    assert profile.declared_conditions(await profile.load_hard_profile(db_user)) == [
        "diabetes",
        "ckd",
    ]


async def test_export_query_runs_against_the_schema(db_user) -> None:
    from backend.db.session import get_session
    from backend.guidelines.export_feedback import export_feedback

    await _add(db_user, DiagnosisValue(condition="ckd"))
    async with get_session()() as session:
        records = await export_feedback(session, rated_only=False, since=None)

    assert isinstance(records, list)
