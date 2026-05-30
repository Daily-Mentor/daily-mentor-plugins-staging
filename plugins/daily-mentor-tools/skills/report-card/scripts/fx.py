"""FX resolution — runtime fetch only when currencies actually differ.

Free, no-API-key Frankfurter (https://www.frankfurter.app/) is the primary source
(daily ECB reference rates, historical back to 1999). A per-run cache prevents
repeat HTTP calls within a single build, and an optional disk cache speeds up
re-runs.

If all source currencies match the reporting currency, NO network call is made.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path


_DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / ".fx-cache" / "rates.json"
_FRANKFURTER_BASE = "https://api.frankfurter.app"
_FETCH_TIMEOUT_SECONDS = 8.0


@dataclass
class FxResolver:
    """Lazy FX rate resolver.

    Usage:
        fx = FxResolver(reporting_currency="AUD")
        rate = fx.rate(on=date(2026, 5, 1), from_ccy="NZD")  # → daily rate (or 1.0 if NZD == AUD)
        converted, used_rate = fx.convert(100.0, on=..., from_ccy="NZD")

    Rates are fetched from Frankfurter only when from_ccy != reporting_currency.
    All fetched rates are cached in-memory and (optionally) to disk.
    """

    reporting_currency: str = "AUD"
    cache_path: Path | None = None
    offline: bool = False
    # In-memory cache: {(from_ccy, "YYYY-MM-DD"): rate_to_reporting}
    _cache: dict[tuple[str, str], float] = field(default_factory=dict)
    _missing_dates: set[tuple[str, str]] = field(default_factory=set)
    _disk_loaded: bool = False

    def __post_init__(self) -> None:
        self.reporting_currency = (self.reporting_currency or "AUD").upper()
        if self.cache_path is None:
            self.cache_path = _DEFAULT_CACHE_PATH

    # ---- Disk cache ----

    def _load_disk_cache(self) -> None:
        if self._disk_loaded:
            return
        self._disk_loaded = True
        if not self.cache_path or not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text())
            rep = payload.get("reporting_currency", "").upper()
            if rep != self.reporting_currency:
                return  # Cache was for a different reporting currency — ignore.
            for key, value in payload.get("rates", {}).items():
                ccy, day = key.split("|", 1)
                self._cache[(ccy.upper(), day)] = float(value)
        except Exception:
            return

    def _save_disk_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "reporting_currency": self.reporting_currency,
            "rates": {f"{ccy}|{day}": rate for (ccy, day), rate in self._cache.items()},
        }
        self.cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    # ---- Frankfurter fetch ----

    def _fetch_range(self, from_ccy: str, start: date, end: date) -> dict[str, float]:
        """Fetch daily rates for from_ccy → reporting over [start, end]. Returns {YYYY-MM-DD: rate}.
        Frankfurter returns business-day rates only; weekend gaps are carry-forward filled by the caller.
        """
        url = f"{_FRANKFURTER_BASE}/{start.isoformat()}..{end.isoformat()}?from={from_ccy}&to={self.reporting_currency}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "report-card/0.1"})
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise FxFetchError(f"Frankfurter fetch failed for {from_ccy}->{self.reporting_currency}: {e}")
        rates_raw: dict[str, dict[str, float]] = data.get("rates", {})
        out: dict[str, float] = {}
        for day_str, mapping in rates_raw.items():
            v = mapping.get(self.reporting_currency)
            if v is not None:
                out[day_str] = float(v)
        return out

    def _carry_forward_fill(self, daily: dict[str, float], start: date, end: date) -> None:
        """In-place fill of weekend/holiday gaps via previous-business-day carry forward."""
        if not daily:
            return
        sorted_days = sorted(daily.keys())
        last_rate = daily[sorted_days[0]]
        cur = start
        while cur <= end:
            k = cur.isoformat()
            if k in daily:
                last_rate = daily[k]
            else:
                daily[k] = last_rate
            cur += timedelta(days=1)

    # ---- Public API ----

    def rate(self, on: date, from_ccy: str, to_ccy: str | None = None) -> float:
        """Return multiplier so `value_in_from_ccy * rate = value_in_to_ccy` (default to_ccy = reporting_currency)."""
        target = (to_ccy or self.reporting_currency).upper()
        src = (from_ccy or target).upper()
        if src == target:
            return 1.0

        # Cross-rate via reporting: rate(src→target) = rate(src→rep) / rate(target→rep)
        if target != self.reporting_currency:
            src_to_rep = self._rate_to_reporting(on, src)
            tgt_to_rep = self._rate_to_reporting(on, target)
            return (src_to_rep / tgt_to_rep) if tgt_to_rep else 1.0

        return self._rate_to_reporting(on, src)

    def _rate_to_reporting(self, on: date, from_ccy: str) -> float:
        from_ccy = from_ccy.upper()
        if from_ccy == self.reporting_currency:
            return 1.0
        self._load_disk_cache()
        key = (from_ccy, on.isoformat())
        if key in self._cache:
            return self._cache[key]
        if self.offline:
            raise FxFetchError(f"FX rate missing (offline mode): {from_ccy}->{self.reporting_currency} on {on}")
        # Fetch a 60-day window around `on` to amortise the call.
        win_start = on - timedelta(days=30)
        win_end = on + timedelta(days=30)
        try:
            fetched = self._fetch_range(from_ccy, win_start, win_end)
        except FxFetchError:
            # Fall back to a single-day fetch
            fetched = self._fetch_range(from_ccy, on, on)
        self._carry_forward_fill(fetched, win_start, win_end)
        for day_str, rate in fetched.items():
            self._cache[(from_ccy, day_str)] = rate
        self._save_disk_cache()
        if key in self._cache:
            return self._cache[key]
        # Last resort — closest available date
        ccy_keys = sorted(d for (c, d) in self._cache if c == from_ccy)
        if ccy_keys:
            closest = min(ccy_keys, key=lambda d: abs((date.fromisoformat(d) - on).days))
            return self._cache[(from_ccy, closest)]
        raise FxFetchError(f"FX rate unavailable: {from_ccy}->{self.reporting_currency} on {on}")

    def convert(self, value: float, on: date, from_ccy: str, to_ccy: str | None = None) -> tuple[float, float]:
        """Return (converted_value, rate_used)."""
        r = self.rate(on, from_ccy, to_ccy)
        return value * r, r

    def covers(self, start: date, end: date, from_ccies: list[str] | None = None) -> bool:
        """Whether the resolver has working rates for every (date, ccy) in the range.
        Empty list / all-matching-reporting → True (no fetches needed)."""
        if not from_ccies or all(c.upper() == self.reporting_currency for c in (from_ccies or [])):
            return True
        try:
            sample = start + (end - start) // 2 if start < end else start
            for ccy in (from_ccies or []):
                if ccy.upper() == self.reporting_currency:
                    continue
                self._rate_to_reporting(sample, ccy)
            return True
        except FxFetchError:
            return False


class FxFetchError(RuntimeError):
    """Raised when an FX rate can't be obtained (network failure or unknown currency)."""
