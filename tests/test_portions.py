from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from nomnomcli.cli import main
from nomnomcli.config import ProviderConfig
from nomnomcli.db import connect, store_log
from nomnomcli.foods import FoodRepository
from nomnomcli.models import Food

BREAKFAST = (
    "3 small fried eggs, half small tomato, half small onion, "
    "whole wheat bread 180 g, milk 110 g, 15 dates"
)
ESTIMATES = {
    "items": [
        {
            "item_index": 0,
            "input": "3 small fried eggs",
            "grams": 135,
            "lower_grams": 120,
            "upper_grams": 150,
            "confidence": 0.72,
            "method": "agent_estimate",
            "assumption": "Three small fried eggs estimated at 45 g each.",
        },
        {
            "item_index": 1,
            "input": "half small tomato",
            "grams": 35,
            "lower_grams": 25,
            "upper_grams": 45,
            "confidence": 0.65,
            "method": "agent_estimate",
            "assumption": "Half of a small tomato estimated at 35 g.",
        },
        {
            "item_index": 2,
            "input": "half small onion",
            "grams": 30,
            "lower_grams": 20,
            "upper_grams": 40,
            "confidence": 0.63,
            "method": "agent_estimate",
            "assumption": "Half of a small onion estimated at 30 g.",
        },
        {
            "item_index": 5,
            "input": "15 dates",
            "grams": 120,
            "lower_grams": 90,
            "upper_grams": 150,
            "confidence": 0.58,
            "method": "agent_estimate",
            "assumption": "Fifteen dates estimated at 8 g each.",
        },
    ]
}


@pytest.fixture
def mocked_generic_breakfast(monkeypatch):
    foods = {
        "fried eggs": Food("egg, fried", 196, 13.6, 14.8, 0.8),
        "tomato": Food("tomato, raw", 18, 0.9, 0.2, 3.9),
        "onion": Food("onion, raw", 40, 1.1, 0.1, 9.3),
        "whole wheat bread": Food("bread, whole wheat", 252, 12, 3.5, 43),
        "milk": Food("milk", 61, 3.2, 3.3, 4.8),
        "dates": Food("dates", 277, 1.8, 0.2, 75),
    }

    def resolve(self, query, *, allow_remote=True):
        del allow_remote
        food = foods[query]
        source_id = str(9000 + list(foods).index(query))
        resolved = Food(
            food.name,
            food.kcal,
            food.protein,
            food.fat,
            food.carbs,
            source="usda",
            fdc_id=int(source_id),
            resolution_mode="generic_proxy",
            source_id=source_id,
            provenance="usda",
            assumption=f"Used mocked USDA generic proxy: {food.name}.",
        )
        self.user_connection.execute(
            """INSERT OR IGNORE INTO food_cache
            (name, kcal, protein, fat, carbs, source, fdc_id, lookup_query,
             resolution_mode, source_id, provenance, assumption)
            VALUES (?, ?, ?, ?, ?, 'usda', ?, ?, 'generic_proxy', ?, 'usda', ?)""",
            (
                resolved.name,
                resolved.kcal,
                resolved.protein,
                resolved.fat,
                resolved.carbs,
                resolved.fdc_id,
                query,
                source_id,
                resolved.assumption,
            ),
        )
        return resolved, 0.91

    monkeypatch.setattr(FoodRepository, "resolve", resolve)


def _log_count(path) -> int:
    if not path.exists():
        return 0
    with connect(path) as connection:
        return int(connection.execute("SELECT count(*) FROM log_entries").fetchone()[0])


def _cache_count(path) -> int:
    if not path.exists():
        return 0
    with connect(path) as connection:
        return int(connection.execute("SELECT count(*) FROM food_cache").fetchone()[0])


def _run_breakfast(user_db, monkeypatch, capsys, estimates=ESTIMATES, *, policy="estimate"):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    arguments = [
        "log",
        "--parse",
        BREAKFAST,
        "--portion-policy",
        policy,
    ]
    if estimates is not None:
        arguments.extend(["--portion-estimates", json.dumps(estimates)])
    arguments.append("--json")
    code = main(arguments)
    return code, capsys.readouterr()


def test_default_strict_breakfast_keeps_piece_weight_unknown_and_writes_no_log(
    user_db, monkeypatch, capsys, mocked_generic_breakfast
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code = main(["log", "--parse", BREAKFAST, "--json"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "piece_weight_unknown"
    assert _log_count(user_db) == 0
    assert _cache_count(user_db) == 0


def test_valid_agent_estimates_log_full_breakfast_and_date_stats_atomically(
    user_db,
    monkeypatch,
    capsys,
    almaty_timezone,
    mocked_generic_breakfast,
):
    monkeypatch.setattr(
        "nomnomcli.cli._local_now",
        lambda: datetime.fromisoformat("2026-07-21T08:30:00+05:00"),
    )
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code = main(
        [
            "log",
            "--parse",
            BREAKFAST,
            "--portion-policy",
            "estimate",
            "--portion-estimates",
            json.dumps(ESTIMATES),
            "--date",
            "2026-07-20",
            "--json",
        ]
    )
    logged = json.loads(capsys.readouterr().out)

    assert code == 0
    assert len(logged["items"]) == 6
    assert logged["approximate"] is True
    assert "scale" in logged["portion_correction"]
    estimated = [
        item for item in logged["items"] if item.get("portion_provenance") == "agent_estimate"
    ]
    assert [item["name"] for item in estimated] == [
        "egg, fried",
        "tomato, raw",
        "onion, raw",
        "dates",
    ]
    assert all(item["approximate"] is True for item in estimated)
    assert all(item["portion_estimate"]["method"] == "agent_estimate" for item in estimated)
    assert all(item["portion_estimate"]["grams"] == item["grams"] for item in estimated)
    assert [item["portion_estimate"]["item_index"] for item in estimated] == [0, 1, 2, 5]
    assert [item["portion_estimate"]["input"] for item in estimated] == [
        "3 small fried eggs",
        "half small tomato",
        "half small onion",
        "15 dates",
    ]
    explicit = [logged["items"][3], logged["items"][4]]
    assert [item["grams"] for item in explicit] == [180, 110]
    assert all("portion_provenance" not in item for item in explicit)
    assert all("approximate" not in item for item in explicit)

    assert main(["stats", "date", "2026-07-20", "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["approximate"] is True
    assert "scale" in stats["portion_correction"]
    assert stats["meals"][0]["approximate"] is True
    assert sum(
        item.get("portion_provenance") == "agent_estimate"
        for item in stats["meals"][0]["items"]
    ) == 4
    assert _log_count(user_db) == 1


def test_text_log_has_one_concise_estimate_correction_prompt(
    user_db, monkeypatch, capsys, mocked_generic_breakfast
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code = main(
        [
            "log",
            "--parse",
            BREAKFAST,
            "--portion-policy",
            "estimate",
            "--portion-estimates",
            json.dumps(ESTIMATES),
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert output.count("Correct approximate portions with scale grams, photo, or barcode.") == 1
    assert "portion: agent_estimate | range 120.00-150.00 g | confidence 0.72" in output
    assert "measured" not in output.casefold()
    assert "exact" not in output.casefold()


def test_ask_policy_requests_external_estimate_without_writing(
    user_db, monkeypatch, capsys, mocked_generic_breakfast
):
    code, captured = _run_breakfast(
        user_db, monkeypatch, capsys, estimates=None, policy="ask"
    )

    error = json.loads(captured.err)["error"]
    assert code == 2
    assert captured.out == ""
    assert error["code"] == "portion_estimate_required"
    assert error["details"]["policy"] == "ask"
    assert error["details"]["item_index"] == 0
    assert error["details"]["input"] == "3 small fried eggs"
    assert _log_count(user_db) == 0
    assert _cache_count(user_db) == 0


def test_estimates_require_explicit_estimate_policy(
    user_db, monkeypatch, capsys, mocked_generic_breakfast
):
    code, captured = _run_breakfast(user_db, monkeypatch, capsys, policy="strict")

    assert code == 2
    assert json.loads(captured.err)["error"]["code"] == "portion_policy_required"
    assert _log_count(user_db) == 0
    assert _cache_count(user_db) == 0


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda payload: payload["items"].pop(), "portion_estimate_missing"),
        (
            lambda payload: payload["items"][0].update({"input": "3 medium fried eggs"}),
            "portion_estimate_mismatch",
        ),
        (
            lambda payload: payload["items"].append(copy.deepcopy(payload["items"][0])),
            "portion_estimate_duplicate",
        ),
        (
            lambda payload: payload["items"][0].update(
                {"lower_grams": 140, "grams": 135}
            ),
            "portion_estimate_invalid",
        ),
        (
            lambda payload: payload["items"][0].update({"confidence": 1.01}),
            "portion_estimate_invalid",
        ),
        (
            lambda payload: payload["items"][0].update({"grams": -1}),
            "portion_estimate_invalid",
        ),
        (
            lambda payload: payload["items"][0].update({"method": "visual_guess"}),
            "portion_estimate_invalid",
        ),
        (
            lambda payload: payload["items"][0].update({"assumption": "  "}),
            "portion_estimate_invalid",
        ),
        (
            lambda payload: payload["items"].append(
                {
                    "item_index": 3,
                    "input": "whole wheat bread 180 g",
                    "grams": 180,
                    "lower_grams": 180,
                    "upper_grams": 180,
                    "confidence": 1,
                    "method": "agent_estimate",
                    "assumption": "Should be rejected because grams were explicit.",
                }
            ),
            "portion_estimate_mismatch",
        ),
    ],
    ids=(
        "missing",
        "input-mismatch",
        "duplicate",
        "range",
        "confidence",
        "negative",
        "method",
        "assumption",
        "estimate-for-explicit-grams",
    ),
)
def test_invalid_or_mismatched_estimate_payload_writes_nothing(
    user_db,
    monkeypatch,
    capsys,
    mocked_generic_breakfast,
    mutation,
    error_code,
):
    payload = copy.deepcopy(ESTIMATES)
    mutation(payload)

    code, captured = _run_breakfast(user_db, monkeypatch, capsys, payload)

    assert code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == error_code
    assert _log_count(user_db) == 0
    assert _cache_count(user_db) == 0


def test_malformed_estimate_json_is_rejected_before_database_creation(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code = main(
        [
            "log",
            "--parse",
            BREAKFAST,
            "--portion-policy",
            "estimate",
            "--portion-estimates",
            '{"items": [',
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert json.loads(captured.err)["error"]["code"] == "portion_estimates_malformed"
    assert not user_db.exists()


def test_explicit_per_piece_grams_remain_authoritative_under_estimate_policy(
    user_db, monkeypatch, capsys, mocked_generic_breakfast
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    code = main(
        [
            "log",
            "--parse",
            "3 pieces fried eggs at 38g",
            "--portion-policy",
            "estimate",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["items"][0]["grams"] == 114
    assert "portion_provenance" not in result["items"][0]
    assert result.get("approximate") is not True


def test_direct_explicit_grams_do_not_read_fuzzy_portion_policy(
    user_db, monkeypatch, capsys, mocked_generic_breakfast
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_PORTION_POLICY", "invalid-for-parse")

    code = main(["log", "--food", "milk", "--grams", "110", "--json"])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["items"][0]["grams"] == 110
    assert "portion_provenance" not in result["items"][0]


def test_legacy_log_items_without_portion_fields_remain_readable(
    user_db, monkeypatch, capsys, almaty_timezone
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        "nomnomcli.cli._local_now",
        lambda: datetime.fromisoformat("2026-07-21T08:30:00+05:00"),
    )
    old_item = {
        "name": "legacy food",
        "grams": 100,
        "kcal": 50,
        "protein": 2,
        "fat": 1,
        "carbs": 8,
        "match_confidence": 1,
    }
    with connect(user_db) as connection:
        store_log(
            connection,
            [old_item],
            {"kcal": 50, "protein": 2, "fat": 1, "carbs": 8},
            logged_at=datetime.fromisoformat("2026-07-20T12:00:00+05:00"),
        )

    assert main(["stats", "date", "2026-07-20", "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)

    assert stats["meals"][0]["items"] == [old_item]
    assert stats["meals"][0]["approximate"] is False
    assert stats["approximate"] is False


def test_portion_policy_defaults_to_strict_and_supports_config_and_env(tmp_path):
    path = tmp_path / "config.toml"
    assert ProviderConfig(environ={}, config_path=path).portion_policy() == "strict"

    path.write_text('[resolution]\nportion_policy = "ask"\n', encoding="utf-8")
    assert ProviderConfig(environ={}, config_path=path).portion_policy() == "ask"
    assert (
        ProviderConfig(
            environ={"NOMNOM_PORTION_POLICY": "estimate"}, config_path=path
        ).portion_policy()
        == "estimate"
    )


def test_storing_usda_key_preserves_portion_policy(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[resolution]\nportion_policy = "estimate"\n', encoding="utf-8")
    config = ProviderConfig(environ={}, config_path=path)

    config.store_usda_key("stored-placeholder")

    assert config.portion_policy() == "estimate"
