from __future__ import annotations

import json
from datetime import datetime

import pytest
import requests

from nomnomcli.cli import main
from nomnomcli.db import connect, store_log
from nomnomcli.errors import NomnomError
from nomnomcli.models import Food
from nomnomcli.off import OpenFoodFactsClient


def _strict_json_loads(value: str) -> dict:
    def reject_constant(constant: str) -> None:
        pytest.fail(f"Non-finite constant in JSON output: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def test_cli_mocked_off_egg_dish_uses_runtime_serving_weight(
    user_db, monkeypatch, capsys, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": [food_fixtures["off"]["egg"]]}

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    code = main(["log", "--parse", "яичница из 3 небольших яиц", "--json"])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["items"][0]["grams"] == 150
    assert result["items"][0]["source"] == "openfoodfacts"


def test_cli_mocked_cheese_for_pine_nuts_is_low_confidence_without_writes(
    user_db, monkeypatch, capsys, food_fixtures
):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": [food_fixtures["off"]["cheese"]]}

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    code = main(["log", "--parse", "кедровые орехи 30 г", "--json"])
    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert error["error"]["code"] == "food_needs_source"
    assert error["error"]["candidate"]["name"] == "Cheese — Wrong Match"
    assert error["error"]["alternatives"] == []
    assert error["error"]["details"]["provider_error"]["code"] == "off_low_confidence"
    assert error["error"]["details"]["candidate"]["name"] == "Cheese — Wrong Match"
    assert "alternatives" in error["error"]["details"]
    with connect(user_db) as connection:
        assert connection.execute("SELECT count(*) FROM food_cache").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM log_entries").fetchone()[0] == 0


def test_cli_no_usda_key_is_actionable_json_error(user_db, monkeypatch, capsys):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"products": []}

    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.delenv("NOMNOM_USDA_KEY", raising=False)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())

    code = main(["log", "--food", "chickpeas cooked", "--grams", "100", "--json"])
    captured = capsys.readouterr()
    error = json.loads(captured.err)

    assert code == 2
    assert captured.out == ""
    assert error["error"]["code"] == "food_needs_source"
    details = error["error"]["details"]
    assert "photo" in details["source_options"]
    assert "barcode" in details["source_options"]
    assert "capture_label" in details["source_options"]
    assert details["optional_usda_enhancement"]["optional"] is True


def test_cli_log_and_stats_json(seeded_user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    code = main(["log", "--parse", "борщ 300г, хлеб 2 куска, гречка 150 г", "--json"])
    logged = json.loads(capsys.readouterr().out)
    assert code == 0
    assert logged["totals"]["kcal"] == 454.2
    assert [item["grams"] for item in logged["items"]] == [300, 60, 150]

    code = main(["stats", "today", "--json"])
    stats = json.loads(capsys.readouterr().out)
    assert code == 0
    assert stats["totals"] == logged["totals"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--parse", "борщ 100 г"],
        ["--food", "borscht", "--grams", "100"],
    ],
    ids=("parsed", "direct"),
)
def test_cli_backdated_log_uses_local_noon_and_returns_effective_date(
    seeded_user_db, monkeypatch, capsys, almaty_timezone, arguments
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    monkeypatch.setattr(
        "nomnomcli.cli._local_now",
        lambda: datetime.fromisoformat("2026-07-21T08:30:00+05:00"),
        raising=False,
    )

    code = main(["log", *arguments, "--date", "2026-07-20", "--json"])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["logged_at"] == "2026-07-20T12:00:00+05:00"
    assert result["local_date"] == "2026-07-20"
    with connect(seeded_user_db) as connection:
        row = connection.execute("SELECT logged_at FROM log_entries").fetchone()
    assert row["logged_at"] == result["logged_at"]


def test_cli_log_without_date_keeps_current_time_behavior_and_returns_effective_date(
    seeded_user_db, monkeypatch, capsys, almaty_timezone
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    monkeypatch.setattr(
        "nomnomcli.cli._local_now",
        lambda: datetime.fromisoformat("2026-07-21T08:34:56+05:00"),
        raising=False,
    )

    assert main(["log", "--food", "borscht", "--grams", "100", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["logged_at"] == "2026-07-21T08:34:56+05:00"
    assert result["local_date"] == "2026-07-21"


def test_cli_explicit_today_is_allowed(
    seeded_user_db, monkeypatch, capsys, almaty_timezone
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    monkeypatch.setattr(
        "nomnomcli.cli._local_now",
        lambda: datetime.fromisoformat("2026-07-21T08:34:56+05:00"),
        raising=False,
    )

    assert (
        main(
            [
                "log",
                "--food",
                "borscht",
                "--grams",
                "100",
                "--date",
                "2026-07-21",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)

    assert result["logged_at"] == "2026-07-21T12:00:00+05:00"
    assert result["local_date"] == "2026-07-21"


@pytest.mark.parametrize(
    ("value", "error_code"),
    [
        ("20-07-2026", "invalid_date"),
        ("2026-07-20T10:30:00", "invalid_date"),
        ("2026-02-30", "invalid_date"),
        ("2026-07-22", "future_date"),
    ],
)
def test_cli_invalid_or_future_log_date_is_actionable_and_makes_no_write(
    user_db, monkeypatch, capsys, almaty_timezone, value, error_code
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        "nomnomcli.cli._local_now",
        lambda: datetime.fromisoformat("2026-07-21T08:30:00+05:00"),
        raising=False,
    )

    code = main(
        ["log", "--food", "anything", "--grams", "100", "--date", value, "--json"]
    )
    captured = capsys.readouterr()
    error = json.loads(captured.err)["error"]

    assert code == 2
    assert captured.out == ""
    assert error["code"] == error_code
    assert error["details"]["value"] == value
    assert error["details"]["expected_format"] == "YYYY-MM-DD"
    assert error["details"]["action"]
    assert not user_db.exists()


def test_cli_stats_date_returns_only_requested_local_day(
    user_db, monkeypatch, capsys, almaty_timezone
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setattr(
        "nomnomcli.cli._local_now",
        lambda: datetime.fromisoformat("2026-07-21T08:30:00+05:00"),
        raising=False,
    )
    item = {
        "name": "test food",
        "grams": 100.0,
        "kcal": 55.0,
        "protein": 2.5,
        "fat": 2.1,
        "carbs": 6.4,
        "match_confidence": 1.0,
    }
    totals = {"kcal": 55.0, "protein": 2.5, "fat": 2.1, "carbs": 6.4}
    with connect(user_db) as connection:
        store_log(
            connection,
            [item],
            totals,
            logged_at=datetime.fromisoformat("2026-07-20T12:00:00+05:00"),
        )
        store_log(
            connection,
            [item],
            totals,
            logged_at=datetime.fromisoformat("2026-07-21T00:00:00+05:00"),
        )

    code = main(["stats", "date", "2026-07-20", "--json"])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["local_date"] == "2026-07-20"
    assert result["totals"]["kcal"] == 55
    assert [meal["logged_at"] for meal in result["meals"]] == [
        "2026-07-20T12:00:00+05:00"
    ]


def test_cli_unknown_food_json_error(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    code = main(["log", "--parse", "неведомая штука 50 г", "--json"])
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert code == 2
    assert captured.out == ""
    assert error["error"]["code"] == "food_needs_source"


def test_cli_direct_requires_grams(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(["log", "--food", "borscht", "--json"])
    error = json.loads(capsys.readouterr().err)
    assert code == 2
    assert error["error"]["code"] == "grams_required"


def test_cli_direct_rejects_non_finite_grams_before_any_write(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "missing" / "user.sqlite3"
    monkeypatch.setenv("NOMNOM_DB_PATH", str(database))

    code = main(["log", "--food", "borscht", "--grams", "1e309", "--json"])
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)["error"]

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["code"] == "invalid_quantity"
    assert error["details"]["would_write"] is False
    assert not database.parent.exists()
    assert not database.exists()


def test_cli_stats_rejects_persisted_non_finite_result_with_strict_json_error(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    with connect(user_db) as connection:
        store_log(
            connection,
            [
                {
                    "name": "legacy food",
                    "grams": 100.0,
                    "kcal": 55.0,
                    "protein": 2.5,
                    "fat": 2.1,
                    "carbs": 6.4,
                    "match_confidence": 1.0,
                }
            ],
            {"kcal": 55.0, "protein": 2.5, "fat": 2.1, "carbs": 6.4},
        )
        connection.execute("UPDATE log_entries SET kcal = ?", (float("inf"),))

    code = main(["stats", "today", "--json"])
    captured = capsys.readouterr()
    error = _strict_json_loads(captured.err)["error"]

    assert code == 2
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert error["code"] == "non_finite_result"
    assert error["details"]["would_write"] is False


def test_cli_search_json(seeded_user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    code = main(["search", "борщ", "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result[0] == {
        "name": "borscht",
        "kcal_per_100g": 55.0,
        "protein_per_100g": 2.5,
        "fat_per_100g": 2.1,
        "carbs_per_100g": 6.4,
    }


def test_cli_json_and_text_surface_size_assumptions(
    seeded_user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    phrase = "омлет из 2 small eggs, half small fixture pod"

    code = main(["log", "--parse", phrase, "--json"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["assumptions"] == [
        "2 small eggs = 100g (source: fixture.synthetic_serving=50 g)",
        "1/2 small fixture pod = 50g (source: fixture.synthetic_serving=100 g)",
    ]
    assert all(item["assumed"] is True for item in result["items"])

    code = main(["log", "--parse", phrase])
    output = capsys.readouterr().out
    assert code == 0
    assert "Assumptions:" in output
    assert "2 small eggs = 100g (source: fixture.synthetic_serving=50 g)" in output


def test_cli_add_pins_branded_product_for_offline_piece_lookup(
    user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(
        [
            "add",
            "--name",
            "хлеб",
            "--brand",
            "harry's",
            "--kcal",
            "250",
            "--protein",
            "9",
            "--fat",
            "4",
            "--carbs",
            "45",
            "--piece-grams",
            "40",
            "--json",
        ]
    )
    added = json.loads(capsys.readouterr().out)
    assert code == 0
    assert added["source"] == "user"
    assert added["piece_grams"] == 40

    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    code = main(["log", "--parse", "хлеб harry's 2 куска", "--json"])
    logged = json.loads(capsys.readouterr().out)
    assert code == 0
    assert logged["items"][0]["grams"] == 80
    assert logged["items"][0]["name"] == "хлеб — harry's"


def test_cli_add_rejects_invalid_nutrition(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    code = main(
        [
            "add",
            "--name",
            "test",
            "--brand",
            "brand",
            "--kcal",
            "-1",
            "--protein",
            "0",
            "--fat",
            "0",
            "--carbs",
            "0",
            "--json",
        ]
    )
    error = json.loads(capsys.readouterr().err)
    assert code == 2
    assert error["error"]["code"] == "invalid_nutrition"


def test_exact_issue_phrase_with_pinned_brand(seeded_user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))
    assert (
        main(
            [
                "add",
                "--name",
                "harry's sandwich bread",
                "--brand",
                "Harry's",
                "--kcal",
                "265",
                "--protein",
                "8",
                "--fat",
                "3.2",
                "--carbs",
                "49",
                "--piece-grams",
                "40",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")
    phrase = (
        "яичница из 3 небольших яиц, half small fixture pod и half medium "
        "fixture bulb, хлеб harry's 2 куска по 40г"
    )
    assert main(["log", "--parse", phrase, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [item["grams"] for item in result["items"]] == [150, 50, 40, 80]
    assert result["items"][3]["name"] == "harry's sandwich bread — Harry's"
    assert result["items"][3]["source"] == "user"
    assert all(
        not item["name"].startswith("oil,") and not item["name"].endswith(" oil")
        for item in result["items"]
    )
    assert result["assumptions"] == [
        "3 small яиц = 150g (source: fixture.synthetic_serving=50 g)",
        "1/2 small fixture pod = 50g (source: fixture.synthetic_serving=100 g)",
        "1/2 medium fixture bulb = 40g (source: fixture.synthetic_serving=80 g)",
    ]


def test_cli_leading_piece_count_with_explicit_grams_is_114g(
    seeded_user_db, monkeypatch, capsys
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(seeded_user_db))

    assert (
        main(
            [
                "log",
                "--parse",
                "3 pieces egg whole boiled at 38g",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["items"][0]["grams"] == 114
    assert "assumptions" not in result


def test_cli_doctor_json_contract(monkeypatch, capsys):
    expected = {
        "providers": {
            "openfoodfacts": {
                "configured": True,
                "product_lookup_reachable": True,
                "full_text_search_ready": False,
            },
            "usda": {
                "configured": False,
                "reachable": False,
                "key_source": None,
            },
        }
    }
    monkeypatch.setattr("nomnomcli.cli.doctor_report", lambda: expected)

    assert main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_cli_setup_passes_noninteractive_state_and_is_actionable(
    monkeypatch, capsys
):
    class NonInteractive:
        def isatty(self):
            return False

    def setup(*, interactive):
        assert interactive is False
        raise NomnomError(
            "setup_requires_interactive",
            "interactive terminal required",
            details={"action": "Run nomnom setup in an interactive terminal"},
        )

    monkeypatch.setattr("nomnomcli.cli.sys.stdin", NonInteractive())
    monkeypatch.setattr("nomnomcli.cli.setup_providers", setup)

    assert main(["setup"]) == 2
    captured = capsys.readouterr()
    assert "Optional: connect USDA for broader no-photo generic/raw-food coverage." in captured.out
    assert "Open Food Facts: free, no account or key" in captured.out
    assert json.loads(captured.err)["error"]["code"] == "setup_requires_interactive"


def test_cli_setup_explains_independent_off_statuses(monkeypatch, capsys):
    class Interactive:
        def isatty(self):
            return True

    monkeypatch.setattr("nomnomcli.cli.sys.stdin", Interactive())
    monkeypatch.setattr(
        "nomnomcli.cli.setup_providers",
        lambda *, interactive: {
            "providers": {
                "openfoodfacts": {
                    "configured": True,
                    "product_lookup_reachable": True,
                    "full_text_search_ready": False,
                },
                "usda": {
                    "configured": True,
                    "reachable": True,
                    "key_source": "environment",
                },
            }
        },
    )

    assert main(["setup"]) == 0
    output = capsys.readouterr().out
    assert "One-time connection" in output
    assert "no-label generic-food lookup" in output
    assert "https://fdc.nal.usda.gov/api-key-signup.html" in output
    assert "Validating" in output
    assert "Connected" in output
    assert "product/barcode lookup (no key): reachable" in output
    assert "full-text resolution: unavailable" in output
    assert "Product reachability does not imply full-text readiness." in output


def test_cli_setup_status_json_is_prompt_free_and_actionable(monkeypatch, capsys):
    expected = {
        "status": "base_ready",
        "generic_coverage": "base",
        "providers": {
            "openfoodfacts": {
                "configured": True,
                "product_lookup_reachable": True,
                "full_text_search_ready": True,
            },
            "usda": {
                "configured": False,
                "reachable": False,
                "key_source": None,
                "purpose": "no-label generic-food lookup",
                "signup_url": "https://fdc.nal.usda.gov/api-key-signup.html",
                "next_action": {
                    "command": "nomnom setup",
                    "optional": True,
                    "message": (
                        "Optional: connect USDA for broader no-photo raw/generic food coverage."
                    ),
                },
            },
        },
    }
    monkeypatch.setattr("nomnomcli.cli.setup_status_report", lambda: expected)
    monkeypatch.setattr(
        "nomnomcli.cli.setup_providers",
        lambda **_: pytest.fail("status mode must not enter interactive setup"),
    )

    assert main(["setup", "--status", "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == expected


def test_cli_off_alternatives_are_additive_json(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    matches = [
        Food(
            "Acme Bread",
            250,
            9,
            4,
            45,
            source="openfoodfacts",
            barcode="1",
            brand="Acme",
        ),
        Food(
            "Acme Seeded Bread",
            240,
            10,
            5,
            40,
            source="openfoodfacts",
            barcode="2",
            brand="Acme",
        ),
    ]
    monkeypatch.setattr(OpenFoodFactsClient, "search", lambda *args, **kwargs: matches)
    assert main(["log", "--parse", "Acme bread 100 г", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["items"][0]["source"] == "openfoodfacts"
    assert result["items"][0]["barcode"] == "1"
    assert result["items"][0]["alternatives"] == [
        {"name": "Acme Seeded Bread", "brand": "Acme", "barcode": "2"}
    ]


def test_cli_off_failure_is_clear_error_json(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    def unavailable(*args, **kwargs):
        raise NomnomError(
            "openfoodfacts_unavailable",
            "Open Food Facts lookup is unavailable",
            details={"status": 503, "offline_escape": "nomnom add --name NAME ..."},
        )

    monkeypatch.setattr(OpenFoodFactsClient, "search", unavailable)
    assert main(["log", "--parse", "Acme missing 100 г", "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error"]["code"] == "food_needs_source"
    provider_error = error["error"]["details"]["provider_error"]
    assert provider_error["code"] == "openfoodfacts_unavailable"
    assert provider_error["details"]["status"] == 503
    assert "nomnom add" in provider_error["details"]["offline_escape"]


def test_cli_alias_crud_json(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    assert (
        main(
            [
                "add",
                "--name",
                "egg",
                "--brand",
                "Fixture",
                "--kcal",
                "155",
                "--protein",
                "12.58",
                "--fat",
                "10.61",
                "--carbs",
                "1.12",
                "--piece-grams",
                "50",
                "--json",
            ]
        )
        == 0
    )
    canonical_name = json.loads(capsys.readouterr().out)["name"]

    assert main(["alias", "add", "яйцо", canonical_name, "--json"]) == 0
    added = json.loads(capsys.readouterr().out)
    assert added == {"phrase": "яйцо", "canonical_food_name": canonical_name}

    assert main(["alias", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [added]

    assert main(["alias", "remove", "ЯЙЦО", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == added

    assert main(["alias", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.parametrize(
    ("argv", "error_code"),
    [
        (["alias", "add", "яйцо", "missing food", "--json"], "alias_target_not_found"),
        (["alias", "remove", "missing", "--json"], "alias_not_found"),
    ],
)
def test_cli_alias_errors_are_structured_json(
    user_db, monkeypatch, capsys, argv, error_code
):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))

    assert main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == error_code


def test_cli_required_harrys_alias_flow(user_db, monkeypatch, capsys):
    monkeypatch.setenv("NOMNOM_DB_PATH", str(user_db))
    assert (
        main(
            [
                "add",
                "--name",
                "harry's american sandwich",
                "--brand",
                "Harry's",
                "--kcal",
                "265",
                "--protein",
                "8",
                "--fat",
                "3.2",
                "--carbs",
                "49",
                "--piece-grams",
                "40",
                "--json",
            ]
        )
        == 0
    )
    canonical_name = json.loads(capsys.readouterr().out)["name"]
    assert canonical_name == "harry's american sandwich — Harry's"

    assert main(["alias", "add", "хлеб harry's", canonical_name, "--json"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("NOMNOM_OFFLINE", "1")

    assert main(["log", "--parse", "хлеб harry's 2 куска по 40г", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["items"][0]["name"] == canonical_name
    assert result["items"][0]["source"] == "user"
    assert result["items"][0]["grams"] == 80
