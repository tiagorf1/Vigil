from scanner import asset_registry as AR


def test_asset_registry_normalizes_aliases():
    assert AR.normalize("fx") == "forex"
    assert AR.normalize("commodities") == "commodity"
    assert AR.normalize("stocks") == "equity"


def test_asset_registry_symbol_inference():
    assert AR.infer_from_symbol("EURUSD=X") == "forex"
    assert AR.infer_from_symbol("GC=F") == "commodity"
    assert AR.infer_from_symbol("^FTSE") == "index"
    assert AR.infer_from_symbol("BTCUSD") == "crypto"


def test_asset_registry_encodes_behavior():
    assert AR.get("equity").has_fundamentals is True
    assert AR.get("crypto").price_only_score is True
    assert AR.get("forex").has_options is False
