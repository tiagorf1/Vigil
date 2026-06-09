"""Vigil understands typed market names (esp. European/Asian indices)."""

from scanner.universe import _match_named_index


def test_european_named_indices_resolve():
    assert _match_named_index("FTSE 100") == ["^FTSE"]
    assert _match_named_index("dax") == ["^GDAXI"]
    assert _match_named_index("CAC 40") == ["^FCHI"]
    assert "^GDAXI" in _match_named_index("European indices")
    assert len(_match_named_index("europe")) >= 5


def test_asian_and_partial_match():
    assert _match_named_index("nikkei") == ["^N225"]
    assert _match_named_index("ftse 100 index please") == ["^FTSE"]   # substring


def test_unknown_returns_empty():
    assert _match_named_index("semiconductor equipment") == []
    assert _match_named_index("") == []
