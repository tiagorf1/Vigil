"""European index constituent lists."""
from scanner.index_constituents import constituents_for, FTSE_100, DAX_40, CAC_40


def test_named_indices_resolve_to_equity_tickers():
    assert constituents_for("FTSE 100")[:1] == ["AZN.L"]
    assert "SAP.DE" in constituents_for("dax")
    assert "MC.PA" in constituents_for("cac 40")
    assert len(constituents_for("euro stoxx 50")) >= 30


def test_europe_blends_and_substring_matches():
    assert len(constituents_for("europe")) >= 30
    assert constituents_for("ftse 100 please") == FTSE_100   # substring


def test_unknown_returns_none():
    assert constituents_for("nikkei") is None      # Asia -> index symbol path
    assert constituents_for("") is None
    assert constituents_for("semiconductors") is None


def test_no_caret_tickers_so_they_route_as_equities():
    for lst in (FTSE_100, DAX_40, CAC_40):
        assert not any(t.startswith("^") for t in lst)
