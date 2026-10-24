"""Mirror test for ``memory/personalization/rules.py`` (plan 01, R7).

Scope note: no test named ``load_local_rules``, ``save_local_rules``, ``load_facts``,
``save_facts`` or ``merge_facts`` before this file. ``merge_facts`` is the one with real
consequences: it decides whether a freshly extracted fact overwrites an older belief, so
the confidence rule and the key-dropping rule are pinned here. Two rough edges are
asserted as they behave and flagged in the ledger rather than quietly dressed up.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from questorharness.capabilities.memory.personalization import rules as rules_module
from questorharness.capabilities.memory.personalization.rules import (
    load_facts,
    load_local_rules,
    merge_facts,
    save_facts,
    save_local_rules,
)


@pytest.fixture()
def store(tmp_path, monkeypatch) -> Path:
    """Point the module's fixed paths at a private directory."""
    directory = tmp_path / "local_rules"
    monkeypatch.setattr(rules_module, "_RULES_DIR", directory)
    monkeypatch.setattr(rules_module, "_RULES_FILE", directory / "rules.md")
    monkeypatch.setattr(rules_module, "_FACTS_FILE", directory / "facts.json")
    return directory


# --- the rules markdown ---------------------------------------------------


def test_an_absent_rules_file_reads_as_empty_rather_than_raising(store: Path) -> None:
    assert not store.exists()
    assert load_local_rules() == ""
    assert not store.exists()


def test_saving_creates_the_directory_and_stores_the_trimmed_text(store: Path) -> None:
    path = save_local_rules("  prefer terse answers  \n\n")

    assert path.parent == store and store.is_dir()
    assert path.read_text(encoding="utf-8") == "prefer terse answers\n"
    assert load_local_rules() == "prefer terse answers"


def test_saving_empty_text_does_not_invent_content(store: Path) -> None:
    save_local_rules("   ")

    assert load_local_rules() == ""


def test_a_rewrite_replaces_the_previous_rules(store: Path) -> None:
    save_local_rules("first")
    save_local_rules("second")

    assert load_local_rules() == "second"
    assert (store / "rules.md").read_text(encoding="utf-8") == "second\n"


# --- the facts json -------------------------------------------------------


def test_a_missing_facts_file_has_a_well_defined_shape(store: Path) -> None:
    assert load_facts() == {"facts": [], "last_updated": None}


def test_saving_facts_stamps_a_timezone_aware_time_and_keeps_non_ascii(store: Path) -> None:
    save_facts({"facts": [{"key": "语言", "value": "用中文回答"}]})

    raw = (store / "facts.json").read_text(encoding="utf-8")
    assert "语言" in raw  # not escaped into \uXXXX sequences
    loaded = load_facts()
    assert loaded["facts"][0]["value"] == "用中文回答"
    assert datetime.fromisoformat(loaded["last_updated"]).tzinfo is not None


def test_saving_facts_creates_the_directory_on_demand(store: Path) -> None:
    assert not store.exists()
    save_facts({"facts": []})
    assert store.is_dir()


def test_a_corrupt_facts_file_fails_loudly_instead_of_losing_everything(store: Path) -> None:
    store.mkdir(parents=True)
    (store / "facts.json").write_text("{not json", encoding="utf-8")

    # Silent fallback would let a later save overwrite the damaged but readable data,
    # so the refusal is the safer behaviour and is pinned as such.
    with pytest.raises(json.JSONDecodeError):
        load_facts()


# --- merging -------------------------------------------------------------


def test_a_new_key_is_appended_and_the_order_follows_insertion() -> None:
    merged = merge_facts({"facts": [{"key": "a", "value": 1}]}, [{"key": "b", "value": 2}])

    assert [entry["key"] for entry in merged["facts"]] == ["a", "b"]


def test_only_a_falsy_key_is_dropped_a_whitespace_one_becomes_its_own_entry() -> None:
    """Pinned, not blessed: the key is tested for truthiness but never stripped.

    ``"  "`` therefore creates a second bucket beside ``""``, so a fact whose key lost
    its text during extraction can slip through instead of being rejected. Ledger row
    113 records making this symmetric with the stripped lookup the callers assume.
    """
    merged = merge_facts({"facts": [{"key": "a", "value": 1}]}, [{"value": "orphan"}, {"key": "  ", "value": 2}])

    assert [entry["key"] for entry in merged["facts"]] == ["a", "  "]


def test_a_duplicate_key_takes_the_higher_confidence_value() -> None:
    merged = merge_facts(
        {"facts": [{"key": "a", "value": "old", "confidence": 0.9}]},
        [{"key": "a", "value": "new", "confidence": 0.2}],
    )

    assert merged["facts"] == [{"key": "a", "value": "old", "confidence": 0.9}]


def test_an_equal_confidence_lets_the_newer_observation_win() -> None:
    merged = merge_facts(
        {"facts": [{"key": "a", "value": "old", "confidence": 0.5}]},
        [{"key": "a", "value": "new", "confidence": 0.5}],
    )

    assert merged["facts"] == [{"key": "a", "value": "new", "confidence": 0.5}]


def test_a_fact_without_a_confidence_field_uses_zero() -> None:
    merged = merge_facts({"facts": [{"key": "a", "value": "old", "confidence": 0.1}]}, [{"key": "a", "value": "new"}])

    assert merged["facts"] == [{"key": "a", "value": "old", "confidence": 0.1}]


def test_the_merge_keeps_one_entry_per_key_in_first_seen_position() -> None:
    merged = merge_facts(
        {"facts": [{"key": "x", "value": 1}, {"key": "y", "value": 2}]},
        [{"key": "y", "value": 30, "confidence": 1.0}, {"key": "z", "value": 4}],
    )

    assert [entry["key"] for entry in merged["facts"]] == ["x", "y", "z"]
    assert merged["facts"][1]["value"] == 30


def test_merging_nothing_leaves_the_existing_facts_intact() -> None:
    existing = {"facts": [{"key": "a", "value": 1}], "last_updated": "2026-01-01T00:00:00+00:00"}

    merged = merge_facts(existing, [])

    assert merged == {"facts": [{"key": "a", "value": 1}]}


def test_a_stored_entry_without_a_key_is_kept_instead_of_breaking_every_merge() -> None:
    """Fixed (ledger #113): one hand-edited line must not poison memory permanently.

    Facts arrive from a file a human or an older writer may have touched, so the merge
    has to survive a key-less entry. It is kept verbatim rather than dropped -- silently
    deleting a stored fact would be a worse failure than the KeyError it replaces.
    """
    merged = merge_facts({"facts": [{"value": "no key"}, {"key": "a", "value": 1}]}, [{"key": "b", "value": 2}])

    assert merged == {"facts": [{"value": "no key"}, {"key": "a", "value": 1}, {"key": "b", "value": 2}]}


def test_a_stored_entry_whose_key_is_null_or_empty_is_kept_and_not_merged_away() -> None:
    merged = merge_facts({"facts": [{"key": None, "value": 1}, {"key": "", "value": 2}]}, [])

    assert merged["facts"] == [{"key": None, "value": 1}, {"key": "", "value": 2}]


def test_duplicate_stored_keys_still_collapse_onto_one_slot() -> None:
    """The unkeyed fix must not turn into "keep every row": keyed dedup still holds."""
    merged = merge_facts({"facts": [{"key": "a", "value": 1}, {"key": "a", "value": 2}]}, [])

    assert merged["facts"] == [{"key": "a", "value": 2}]


def test_an_unkeyed_stored_entry_still_shares_one_slot_with_a_new_fact() -> None:
    merged = merge_facts(
        {"facts": [{"value": "noise"}, {"key": "a", "value": "old", "confidence": 0.1}]},
        [{"key": "a", "value": "new", "confidence": 0.8}],
    )

    assert merged["facts"] == [{"value": "noise"}, {"key": "a", "value": "new", "confidence": 0.8}]
