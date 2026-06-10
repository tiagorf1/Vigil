"""Central configuration loader.

Reads `.env` (via python-dotenv) once and exposes a frozen `Config` object.
Every other module imports `get_config()` rather than touching os.environ.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (parent of this file's package).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def _get(key: str, default: str = "") -> str:
    value = os.environ.get(key, default).strip()
    if value.startswith("#"):
        return ""
    return value


def _get_int(key: str, default: int) -> int:
    raw = _get(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _get_bool(key: str, default: bool = False) -> bool:
    raw = _get(key).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _expand(path: str) -> str:
    return str(Path(os.path.expanduser(path)).resolve()) if path else path


class ConfigError(RuntimeError):
    """Raised when configuration is invalid in a way that must abort startup."""


@dataclass(frozen=True)
class Config:
    project_root: Path

    # LLM synthesis
    llm_provider: str               # gemini | anthropic | none
    gemini_api_key: str
    fundamentals_provider: str
    fmp_api_key: str
    gemini_model: str
    anthropic_api_key: str
    anthropic_model: str
    anthropic_use_sonnet: bool

    # OpenAlice
    openalice_mcp_url: str
    openalice_backend_url: str

    # Kronos
    kronos_service_port: int
    kronos_model: str
    kronos_tokenizer: str
    kronos_repo_path: str
    kronos_sample_count: int
    kronos_mc_paths: int
    kronos_t: float
    kronos_top_p: float
    kronos_device: str
    kronos_service_url_override: str
    kronos_http_timeout: float
    kronos_screen_paths: int   # stage-1 low-path sweep before refining the buffer

    # Scanner behaviour
    default_lookback: int
    default_pred_len: int
    kronos_horizons: str   # comma list of forecast horizons the system auto-selects from
    max_universe_size: int
    max_index_components_local: int
    max_screened_size: int
    max_watchlist_size: int

    # UI
    ui_port: int
    vigil_worker_url: str   # if set, the local cockpit forwards scans to this cloud worker
    vigil_worker_token: str # shared secret sent as X-Vigil-Token to the worker
    refresh_on_open: bool

    # Telegram signals
    telegram_bot_token: str
    telegram_chat_id: str
    signal_min_conviction: int
    signal_min_return: float
    signal_markets: str          # comma list: world,us,europe,asia,crypto

    # Free OHLCV fallback (Stooq) when OpenAlice has no price history
    use_data_fallback: bool

    # Position sizing
    account_equity: float          # 0 = unknown -> weights only, no dollar amounts
    sizing_kelly_fraction: float   # fraction of full Kelly to use (e.g. 0.5 = half-Kelly)
    sizing_target_vol: float       # annualized portfolio vol target per position

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def kronos_service_url(self) -> str:
        # If a remote service URL is set, use it (offload forecasting elsewhere).
        return self.kronos_service_url_override or f"http://localhost:{self.kronos_service_port}"

    @property
    def kronos_is_remote(self) -> bool:
        return bool(self.kronos_service_url_override)

    @property
    def signal_market_list(self) -> list[str]:
        return [m.strip() for m in self.signal_markets.split(",") if m.strip()]

    @property
    def horizon_list(self) -> list[int]:
        out = []
        for h in self.kronos_horizons.split(","):
            try:
                out.append(int(h.strip()))
            except ValueError:
                continue
        return out or [10, 30, 60]

    @property
    def resolved_anthropic_model(self) -> str:
        if self.anthropic_use_sonnet:
            return "claude-sonnet-4-6"
        return self.anthropic_model or "claude-opus-4-6"

    def require_llm_ready(self) -> None:
        """Abort-condition check: the chosen provider must be usable.

        `none` always passes (it needs no key). gemini/anthropic require a key.
        """
        if self.llm_provider == "none":
            return
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ConfigError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is empty. "
                "Get a free key at https://aistudio.google.com/apikey, or set "
                "LLM_PROVIDER=none to run with the template report."
            )
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ConfigError(
                "LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty. "
                "Set the key, or switch LLM_PROVIDER to gemini/none."
            )
        if self.llm_provider not in {"gemini", "anthropic", "none"}:
            raise ConfigError(
                f"LLM_PROVIDER='{self.llm_provider}' is invalid. "
                "Use gemini, anthropic, or none."
            )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config(
        project_root=_PROJECT_ROOT,
        llm_provider=_get("LLM_PROVIDER", "gemini").lower() or "gemini",
        gemini_api_key=_get("GEMINI_API_KEY"),
        fundamentals_provider=_get("FUNDAMENTALS_PROVIDER", "auto") or "auto",
        fmp_api_key=_get("FMP_API_KEY"),
        gemini_model=_get("GEMINI_MODEL", "gemini-2.5-flash"),
        anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        anthropic_model=_get("ANTHROPIC_MODEL", "claude-opus-4-6"),
        anthropic_use_sonnet=_get_bool("ANTHROPIC_USE_SONNET", False),
        openalice_mcp_url=_get("OPENALICE_MCP_URL", "http://localhost:47332/mcp"),
        openalice_backend_url=_get("OPENALICE_BACKEND_URL", "http://localhost:47331"),
        kronos_service_port=_get_int("KRONOS_SERVICE_PORT", 8765),
        kronos_model=_get("KRONOS_MODEL", "NeoQuasar/Kronos-small"),
        kronos_tokenizer=_get("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base"),
        kronos_repo_path=_expand(_get("KRONOS_REPO_PATH", "~/Kronos")),
        kronos_sample_count=_get_int("KRONOS_SAMPLE_COUNT", 3),
        kronos_mc_paths=_get_int("KRONOS_MC_PATHS", 24),
        kronos_t=float(_get("KRONOS_T", "1.0") or 1.0),
        kronos_top_p=float(_get("KRONOS_TOP_P", "0.95") or 0.95),
        kronos_device=_get("KRONOS_DEVICE", "auto") or "auto",
        kronos_service_url_override=_get("KRONOS_SERVICE_URL"),
        kronos_http_timeout=float(_get("KRONOS_HTTP_TIMEOUT", "5400") or 5400),
        kronos_screen_paths=_get_int("KRONOS_SCREEN_PATHS", 6),
        default_lookback=_get_int("DEFAULT_LOOKBACK", 400),
        default_pred_len=_get_int("DEFAULT_PRED_LEN", 90),
        kronos_horizons=_get("KRONOS_HORIZONS", "10,30,60") or "10,30,60",
        max_universe_size=_get_int("MAX_UNIVERSE_SIZE", 500),
        max_index_components_local=_get_int("MAX_INDEX_COMPONENTS_LOCAL", 120),
        max_screened_size=_get_int("MAX_SCREENED_SIZE", 30),
        max_watchlist_size=_get_int("MAX_WATCHLIST_SIZE", 10),
        ui_port=_get_int("SCANNER_UI_PORT", 8080),
        vigil_worker_url=_get("VIGIL_WORKER_URL"),
        vigil_worker_token=_get("VIGIL_WORKER_TOKEN"),
        refresh_on_open=_get_bool("VIGIL_REFRESH_ON_OPEN", False),
        telegram_bot_token=_get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_get("TELEGRAM_CHAT_ID"),
        signal_min_conviction=_get_int("SIGNAL_MIN_CONVICTION", 4),
        signal_min_return=float(_get("SIGNAL_MIN_RETURN", "6") or 6),
        signal_markets=_get("SIGNAL_MARKETS", "world") or "world",
        use_data_fallback=_get_bool("USE_DATA_FALLBACK", True),
        account_equity=float(_get("VIGIL_ACCOUNT_EQUITY", "0") or 0),
        sizing_kelly_fraction=float(_get("SIZING_KELLY_FRACTION", "0.5") or 0.5),
        sizing_target_vol=float(_get("SIZING_TARGET_VOL", "0.15") or 0.15),
    )
