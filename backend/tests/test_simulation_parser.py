"""Unit tests for the X-Simulate-Failure header parser."""

from app.llm.simulation import parse_simulation_header


def test_parse_single_and_multiple_pairs():
    keys = ["key_1", "key_2"]
    assert parse_simulation_header("key_1=429", keys, enabled=True) == {"key_1": 429}
    assert parse_simulation_header(" key_1 = 429 , key_2 = 500 ", keys, enabled=True) == {
        "key_1": 429,
        "key_2": 500,
    }


def test_parse_wildcard_expands_all_keys():
    keys = ["key_1", "key_2", "key_3"]
    assert parse_simulation_header("*=503", keys, enabled=True) == {
        "key_1": 503,
        "key_2": 503,
        "key_3": 503,
    }


def test_disabled_returns_empty():
    assert parse_simulation_header("key_1=429", ["key_1", "key_2"], enabled=False) == {}


def test_invalid_pairs_statuses_and_unknown_keys_ignored():
    keys = ["key_1", "key_2"]
    assert parse_simulation_header("garbage,key_1=abc,key_99=429,key_2=404", keys, enabled=True) == {}
    assert parse_simulation_header("bad,key_1=502,key_2=200", keys, enabled=True) == {"key_1": 502}

