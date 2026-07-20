from __future__ import annotations

import pytest
import requests

from nomnomcli.errors import NomnomError, ProviderUnavailableError
from nomnomcli.off import OFF_PRODUCT_PROBE_URL, OFF_SEARCH_URL, OpenFoodFactsClient
from nomnomcli.providers import RetryPolicy


class Response:
    def __init__(self, payload=None, *, status_code=200, json_error=None, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload


def product(name="Whole Grain Bread", brand="Acme", code="0123456789012", kcal=250):
    return {
        "product_name": name,
        "brands": brand,
        "code": code,
        "serving_size": "40 g",
        "nutriments": {
            "energy-kcal_100g": kcal,
            "proteins_100g": 9,
            "fat_100g": 4,
            "carbohydrates_100g": 45,
        },
    }


def test_off_v1_full_text_search_uses_official_contract(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response({"products": [product()]})

    monkeypatch.setattr(requests, "get", fake_get)
    foods = OpenFoodFactsClient().search("Acme bread", page_size=3)

    assert OFF_SEARCH_URL == "https://world.openfoodfacts.org/cgi/search.pl"
    assert captured == {
        "url": OFF_SEARCH_URL,
        "params": {
            "search_terms": "Acme bread",
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "fields": (
                "product_name,brands,nutriments,code,serving_size,"
                "categories,categories_tags"
            ),
            "page_size": 3,
        },
        "timeout": 10,
        "headers": {"User-Agent": "nomnomcli/0.3.0 (+https://github.com/maxjustships/nomnomcli)"},
    }
    assert foods[0].name == "Whole Grain Bread — Acme"
    assert foods[0].source == "openfoodfacts"
    assert foods[0].fdc_id is None
    assert foods[0].barcode == "0123456789012"
    assert foods[0].piece_grams == 40
    assert (foods[0].kcal, foods[0].protein, foods[0].fat, foods[0].carbs) == (250, 9, 4, 45)


def test_off_v1_distinct_terms_receive_distinct_results():
    requested_terms = []

    def replay_get(url, **kwargs):
        assert url == OFF_SEARCH_URL
        term = kwargs["params"]["search_terms"]
        requested_terms.append(term)
        return Response({"products": [product(name=f"Result for {term}")]})

    client = OpenFoodFactsClient(request_get=replay_get)

    soy = client.search("soy protein isolate")
    peanuts = client.search("peanuts")

    assert requested_terms == ["soy protein isolate", "peanuts"]
    assert soy[0].name == "Result for soy protein isolate — Acme"
    assert peanuts[0].name == "Result for peanuts — Acme"
    assert soy != peanuts


def test_off_probe_exercises_same_v1_full_text_capability():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"products": []})

    assert OpenFoodFactsClient(request_get=get).probe() is True
    assert len(calls) == 1
    assert calls[0][0] == OFF_SEARCH_URL
    assert {
        "search_terms": "nomnom",
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": 1,
    }.items() <= calls[0][1]["params"].items()
    assert "fields" in calls[0][1]["params"]
    assert "/api/v2/search" not in calls[0][0]


def test_off_product_probe_uses_v2_barcode_endpoint_without_free_text():
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"status": 0})

    assert OpenFoodFactsClient(request_get=get).probe_product() is True
    assert calls == [
        (
            OFF_PRODUCT_PROBE_URL,
            {
                "params": {"fields": "code"},
                "timeout": 10,
                "headers": {
                    "User-Agent": (
                        "nomnomcli/0.3.0 (+https://github.com/maxjustships/nomnomcli)"
                    )
                },
            },
        )
    ]
    assert "search_terms" not in calls[0][1]["params"]


def test_off_rejects_candidate_with_nonpositive_core_nutrient(monkeypatch):
    candidate = product()
    candidate["nutriments"]["fat_100g"] = 0
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: Response({"products": [candidate]}),
    )

    assert OpenFoodFactsClient().search("Acme bread") == []


def test_off_http_503_is_clear(monkeypatch):
    urls = []

    def unavailable(url, **kwargs):
        urls.append(url)
        return Response(status_code=503)

    monkeypatch.setattr(requests, "get", unavailable)
    with pytest.raises(ProviderUnavailableError) as caught:
        OpenFoodFactsClient(sleep=lambda _: None).search("Acme bread")
    assert caught.value.code == "openfoodfacts_unavailable"
    assert caught.value.details["status"] == 503
    assert caught.value.details["attempts"] == 3
    assert caught.value.details["retryable"] is True
    assert "nomnom add" in caught.value.details["offline_escape"]
    assert urls == [OFF_SEARCH_URL, OFF_SEARCH_URL, OFF_SEARCH_URL]
    assert all("/api/v2/search" not in url for url in urls)


def test_off_network_error_is_clear(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(ProviderUnavailableError) as caught:
        OpenFoodFactsClient().search("Acme bread")
    assert caught.value.code == "openfoodfacts_unavailable"
    assert caught.value.details["reason"] == "network_error"
    assert caught.value.retryable is True


def test_off_malformed_json_is_clear(monkeypatch):
    response = Response(json_error=ValueError("not json"))
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(NomnomError) as caught:
        OpenFoodFactsClient().search("Acme bread")
    assert caught.value.code == "openfoodfacts_invalid_response"


def test_off_ambiguous_results_keep_relevance_order(monkeypatch):
    payload = {
        "products": [
            product(name="Best Match", brand="Acme", code="1"),
            product(name="Second Match", brand="Acme", code="2", kcal=240),
        ]
    }
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response(payload))
    foods = OpenFoodFactsClient().search("Acme bread")
    assert [food.barcode for food in foods] == ["1", "2"]


def test_off_retries_429_and_5xx_with_injected_safe_delays():
    responses = iter(
        [
            Response(status_code=429, headers={"Retry-After": "1.5"}),
            Response(status_code=503, headers={"Retry-After": "not-numeric"}),
            Response({"products": [product()]}),
        ]
    )
    calls = []
    sleeps = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    client = OpenFoodFactsClient(
        request_get=get,
        retry_policy=RetryPolicy(max_attempts=3, backoff_base=0.5),
        sleep=sleeps.append,
    )
    assert client.search("Acme bread")[0].barcode == "0123456789012"
    assert len(calls) == 3
    assert sleeps == [1.5, 1.0]
    assert all(call[0] == OFF_SEARCH_URL for call in calls)


def test_off_oversized_retry_after_uses_bounded_backoff():
    responses = iter(
        [
            Response(status_code=503, headers={"Retry-After": "999999"}),
            Response({"products": []}),
        ]
    )
    sleeps = []
    client = OpenFoodFactsClient(
        request_get=lambda *args, **kwargs: next(responses),
        retry_policy=RetryPolicy(max_attempts=2, backoff_base=0.25, max_retry_after=5),
        sleep=sleeps.append,
    )
    assert client.search("Acme bread") == []
    assert sleeps == [0.25]
