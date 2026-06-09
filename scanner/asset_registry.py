"""One place for asset-class behavior.

Vigil scans very different markets. Equities, ETFs, crypto, FX, commodities and
indexes should not all pretend to have the same fundamentals, trading hours, or
options availability. This registry is the lightweight contract other modules
can consult before deciding how to screen, score, or express a trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssetSpec:
    name: str
    label: str
    has_fundamentals: bool
    price_only_score: bool
    has_options: bool
    trades_24_7: bool = False
    default_universe: str = "seed"
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    hygiene: dict = field(default_factory=dict)


REGISTRY: dict[str, AssetSpec] = {
    "equity": AssetSpec(
        name="equity",
        label="Equity",
        has_fundamentals=True,
        price_only_score=False,
        has_options=True,
        default_universe="large_liquid_equities",
        risk_notes=("earnings_gap_risk", "single_name_idiosyncratic_risk"),
        hygiene={"min_bars": 180, "min_price": 3.0, "options_min_open_interest": 100},
    ),
    "etf": AssetSpec(
        name="etf",
        label="ETF",
        has_fundamentals=False,
        price_only_score=True,
        has_options=True,
        default_universe="liquid_etfs",
        risk_notes=("underlying_exposure_overlap", "tracking_error"),
        hygiene={"min_bars": 180, "min_price": 5.0, "options_min_open_interest": 100},
    ),
    "index": AssetSpec(
        name="index",
        label="Index",
        has_fundamentals=False,
        price_only_score=True,
        has_options=False,
        default_universe="named_indexes",
        risk_notes=("not_directly_tradeable_without_etf_or_future", "macro_beta"),
        hygiene={"min_bars": 180},
    ),
    "crypto": AssetSpec(
        name="crypto",
        label="Crypto",
        has_fundamentals=False,
        price_only_score=True,
        has_options=False,
        trades_24_7=True,
        default_universe="coingecko_top",
        risk_notes=("weekend_liquidity", "exchange_fragmentation", "regulatory_event_risk"),
        hygiene={"min_bars": 180},
    ),
    "commodity": AssetSpec(
        name="commodity",
        label="Commodity",
        has_fundamentals=False,
        price_only_score=True,
        has_options=False,
        default_universe="front_month_futures",
        risk_notes=("roll_yield", "inventory_or_weather_shock", "contract_calendar"),
        hygiene={"min_bars": 180},
    ),
    "forex": AssetSpec(
        name="forex",
        label="FX",
        has_fundamentals=False,
        price_only_score=True,
        has_options=False,
        default_universe="major_pairs",
        risk_notes=("central_bank_event_risk", "rate_differential", "session_liquidity"),
        hygiene={"min_bars": 180},
    ),
}


def get(asset_class: str | None) -> AssetSpec:
    return REGISTRY.get(normalize(asset_class), REGISTRY["equity"])


def normalize(asset_class: str | None) -> str:
    ac = (asset_class or "equity").lower().strip()
    aliases = {
        "stock": "equity",
        "stocks": "equity",
        "fx": "forex",
        "currency": "forex",
        "currencies": "forex",
        "cmdty": "commodity",
        "commodities": "commodity",
        "future": "commodity",
        "futures": "commodity",
        "indices": "index",
        "indexes": "index",
    }
    return aliases.get(ac, ac if ac in REGISTRY else "equity")


def infer_from_symbol(symbol: str) -> str:
    up = (symbol or "").upper()
    if up.endswith("=X"):
        return "forex"
    if up.endswith("=F"):
        return "commodity"
    if up.startswith("^"):
        return "index"
    if up.endswith(("USD", "USDT")):
        return "crypto"
    if up in {"SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "USO"}:
        return "etf"
    return "equity"
