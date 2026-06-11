"""Korea Hydrographic and Oceanographic Agency (KHOA) Open API client.

This client wraps the *국가중점 데이터* APIs registered on data.go.kr:

    * tide_hourly      1시간 조위 (조석성과)          ← validation target
    * tide_deviation   편차계산표 (조석성과)
    * tide_extreme     최극조위 (조석성과)
    * msl              평균해면성과표

Authentication
--------------
All endpoints share a single ``ServiceKey`` issued by data.go.kr.
Provide it via the ``KHOA_API_KEY`` environment variable, or pass
``api_key=`` explicitly. Both URL-encoded and decoded forms of the key are
accepted by KHOA; this client passes it verbatim.

Endpoint configuration
----------------------
Exact REST URLs are defined in ``config/khoa_apis.yaml``. If your
data.go.kr dashboard shows a different URL pattern, edit that YAML file
rather than this module.

Caching
-------
Each ``(api_id, ObsCode, Date)`` request is cached on disk under
``data/raw/khoa/<api_id>/<ObsCode>_<Date>.json`` to keep within the
10 000 requests/day quota.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
import yaml

from ..config import CONFIG_DIR

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

KHOA_CONFIG_PATH = CONFIG_DIR / "khoa_apis.yaml"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config() -> dict[str, Any]:
    with open(KHOA_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get("KHOA_API_KEY")
    if not key:
        raise RuntimeError(
            "KHOA API key required. Set KHOA_API_KEY environment variable "
            "or pass api_key= explicitly."
        )
    return key


def _api_key_optional(explicit: str | None) -> str | None:
    """Return the key if available, else ``None`` (used for cache-only paths)."""
    return explicit or os.environ.get("KHOA_API_KEY")


def _resolve_path(payload: dict, path: list[str]) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_present(record: dict, candidates: list[str]) -> Any:
    for key in candidates:
        if key in record and record[key] not in ("", None):
            return record[key]
    return None


# ---------------------------------------------------------------------------
# Generic request layer
# ---------------------------------------------------------------------------

def _extract_rows(payload: Any, cfg: dict) -> list[dict]:
    """Try each envelope-path candidate until one yields a non-empty list."""
    candidates = cfg.get("envelope", {}).get("candidates") or [
        ["response", "body", "items", "item"],
        ["response", "body", "items"],
        ["result", "data"],
        ["data"],
        ["items"],
    ]
    best: list[dict] = []
    for path in candidates:
        rows = _resolve_path(payload, path)
        if rows is None:
            continue
        if isinstance(rows, dict):
            rows = [rows]
        if isinstance(rows, list) and len(rows) > len(best):
            best = rows
    return best


def _result_code(payload: Any, cfg: dict) -> tuple[str | None, str | None]:
    env = cfg.get("envelope", {})

    code = None
    for path in env.get("result_code_candidates", []) or [env.get("result_code_path", [])]:
        if path:
            code = _resolve_path(payload, path)
            if code is not None:
                break

    msg = None
    for path in env.get("result_msg_candidates", []) or [env.get("result_msg_path", [])]:
        if path:
            msg = _resolve_path(payload, path)
            if msg is not None:
                break

    return (str(code) if code is not None else None,
            str(msg) if msg is not None else None)


def _build_params(
    spec: dict,
    common: dict,
    api_key: str,
    obs_code: str,
    req_date: str | None,
) -> dict:
    p = dict(common or {})
    params_spec = spec.get("params", {})
    pkey = params_spec.get("key_name", "obsCode")
    pdate = params_spec.get("date_name")  # may be None for APIs without reqDate
    p[pkey] = obs_code
    if pdate and req_date is not None:
        p[pdate] = req_date
    p["serviceKey"] = api_key
    return p


def _total_count(payload: Any) -> int | None:
    """Try several common locations for totalCount."""
    for path in (
        ["body", "totalCount"],
        ["response", "body", "totalCount"],
    ):
        v = _resolve_path(payload, path)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


def _request_single_page(
    api_id: str,
    obs_code: str,
    req_date: str | None,
    api_key: str,
    cfg: dict,
    page: int = 1,
    timeout: int = 30,
) -> tuple[list[dict], int | None]:
    """Single-page request. Returns (rows, total_count)."""
    spec = cfg["apis"][api_id]
    url = cfg["base"]["url"].rstrip("/") + spec["path"]
    params = _build_params(spec, cfg.get("common_params", {}), api_key, obs_code, req_date)
    params["pageNo"] = str(page)

    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()

    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        snippet = resp.text[:200]
        raise RuntimeError(
            f"KHOA {api_id}: non-JSON response. First 200 chars: {snippet!r}"
        ) from exc

    code, msg = _result_code(payload, cfg)
    env = cfg.get("envelope", {})
    ok = env.get("ok_codes", ["00", "0"])
    nodata = env.get("nodata_codes", ["03", "3"])
    if code is not None and code not in ok:
        level = logging.INFO if code in nodata else logging.WARNING
        log.log(level, "KHOA %s p=%d: resultCode=%s (%s)", api_id, page, code, msg)
    return _extract_rows(payload, cfg), _total_count(payload)


def _request(
    api_id: str,
    obs_code: str,
    req_date: str | None,
    api_key: str,
    cfg: dict,
    timeout: int = 30,
) -> list[dict]:
    """Issue a paginated KHOA request and return all rows across pages."""
    page_size = int(cfg.get("common_params", {}).get("numOfRows", 300))
    all_rows, total = _request_single_page(api_id, obs_code, req_date, api_key, cfg, page=1, timeout=timeout)

    if total is None or total <= len(all_rows):
        return all_rows

    pages_needed = (total + page_size - 1) // page_size
    for p in range(2, pages_needed + 1):
        rows, _ = _request_single_page(api_id, obs_code, req_date, api_key, cfg, page=p, timeout=timeout)
        if not rows:
            break
        all_rows.extend(rows)
    log.info("KHOA %s: paginated %d rows across %d pages (totalCount=%d)",
             api_id, len(all_rows), pages_needed, total)
    return all_rows


def _request_cached(
    api_id: str,
    obs_code: str,
    req_date: str | None,
    api_key: str | None,
    cfg: dict,
    cache_dir: Path,
) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = req_date if req_date else "all"
    cache_path = cache_dir / api_id / f"{obs_code}_{suffix}.json"
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Only require an API key on a cache miss; offline/cache-only callers
    # rely on this so they can re-use the bundled KHOA cache without secrets.
    if api_key is None:
        raise RuntimeError(
            f"KHOA cache miss for {api_id}/{obs_code}_{suffix}.json and no "
            "API key available to fetch it. Set KHOA_API_KEY or warm the cache."
        )

    rows = _request(api_id, obs_code, req_date, api_key, cfg)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    return rows


# ---------------------------------------------------------------------------
# API: tide_hourly  (1시간 조위)
# ---------------------------------------------------------------------------

def _parse_kst_to_utc(t_str: str) -> datetime | None:
    if t_str is None:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            t = datetime.strptime(t_str, fmt).replace(tzinfo=KST)
            return t.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        # ISO fallback (may already include timezone info)
        t = datetime.fromisoformat(t_str)
        if t.tzinfo is None:
            t = t.replace(tzinfo=KST)
        return t.astimezone(timezone.utc)
    except ValueError:
        return None


def _normalise_hourly_rows(rows: list[dict], spec: dict) -> pd.DataFrame:
    keys = spec["response_keys"]
    records: list[dict] = []
    for r in rows:
        t_raw = _first_present(r, keys["record_time"])
        v_raw = _first_present(r, keys["tide_cm"])
        if t_raw is None or v_raw is None:
            continue
        t_utc = _parse_kst_to_utc(str(t_raw))
        if t_utc is None:
            continue
        try:
            tide_m = float(v_raw) / 100.0
        except (TypeError, ValueError):
            continue
        records.append({"datetime_utc": t_utc, "tide_m": tide_m})
    if not records:
        return pd.DataFrame({"datetime_utc": pd.to_datetime([], utc=True), "tide_m": []})
    return pd.DataFrame(records).sort_values("datetime_utc").reset_index(drop=True)


def fetch_tide_hourly(
    station_code: str,
    day: date,
    cache_dir: Path,
    api_key: str | None = None,
    cfg: dict | None = None,
) -> pd.DataFrame:
    """Fetch one day of QC'd 1-hour tide observations.

    Returns a DataFrame with columns ``datetime_utc`` and ``tide_m``.
    """
    cfg = cfg or _load_config()
    key = _api_key_optional(api_key)
    rows = _request_cached("tide_hourly", station_code, day.strftime("%Y%m%d"), key, cfg, cache_dir)
    return _normalise_hourly_rows(rows, cfg["apis"]["tide_hourly"])


def fetch_tide_hourly_range(
    station_code: str,
    start: date,
    end: date,
    cache_dir: Path,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch a date range, one API call per day."""
    cfg = _load_config()
    frames: list[pd.DataFrame] = []
    cur = start
    while cur <= end:
        try:
            df_day = fetch_tide_hourly(station_code, cur, cache_dir, api_key, cfg)
        except requests.HTTPError as exc:
            log.warning("KHOA HTTP %s %s: %s", station_code, cur, exc)
            df_day = pd.DataFrame(columns=["datetime_utc", "tide_m"])
        except Exception as exc:  # noqa: BLE001
            log.warning("KHOA parse error %s %s: %s", station_code, cur, exc)
            df_day = pd.DataFrame(columns=["datetime_utc", "tide_m"])
        frames.append(df_day)
        cur += timedelta(days=1)

    if not frames:
        return pd.DataFrame({"datetime_utc": pd.to_datetime([], utc=True), "tide_m": []})
    out = pd.concat(frames, ignore_index=True)
    out["datetime_utc"] = pd.to_datetime(out["datetime_utc"], utc=True, errors="coerce")
    out = out.dropna(subset=["datetime_utc"])
    out = out.drop_duplicates("datetime_utc")
    return out.sort_values("datetime_utc").reset_index(drop=True)


# ---------------------------------------------------------------------------
# API: tide_deviation, tide_extreme, msl
# ---------------------------------------------------------------------------

def fetch_deviation_table(
    station_code: str,
    req_date: str,
    cache_dir: Path,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch the KHOA observed/predicted deviation table.

    ``req_date`` format depends on the API (typically YYYYMM or YYYYMMDD).
    """
    cfg = _load_config()
    rows = _request_cached(
        "tide_deviation", station_code, req_date, _api_key(api_key), cfg, cache_dir
    )
    return pd.DataFrame(rows)


def fetch_extreme_tides(
    station_code: str,
    cache_dir: Path,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch monthly/yearly extreme tides (no reqDate; returns full history)."""
    cfg = _load_config()
    rows = _request_cached(
        "tide_extreme", station_code, None, _api_key(api_key), cfg, cache_dir
    )
    return pd.DataFrame(rows)


def fetch_msl(
    station_code: str,
    cache_dir: Path,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Fetch monthly mean sea level (no reqDate; returns full history)."""
    cfg = _load_config()
    rows = _request_cached(
        "msl", station_code, None, _api_key(api_key), cfg, cache_dir
    )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Interpolation helper (unchanged from previous version)
# ---------------------------------------------------------------------------

def interpolate_at_times(
    obs: pd.DataFrame,
    target_times: Iterable[pd.Timestamp],
    max_gap_minutes: int = 90,
) -> pd.Series:
    """Linearly interpolate KHOA observations to target timestamps.

    ``max_gap_minutes`` defaults to 90 (suitable for 1-hour QC data).
    """
    target = pd.to_datetime(pd.Index(list(target_times)), utc=True)
    if obs.empty:
        return pd.Series([float("nan")] * len(target), index=target, dtype=float)

    obs_sorted = obs.sort_values("datetime_utc").drop_duplicates("datetime_utc")
    obs_times = pd.to_datetime(obs_sorted["datetime_utc"], utc=True).reset_index(drop=True)
    obs_vals = obs_sorted["tide_m"].to_numpy()

    out = pd.Series(index=target, dtype=float)
    idx_right = obs_times.searchsorted(target, side="left")

    for i, t in enumerate(target):
        r = int(idx_right[i])
        if r == 0 or r >= len(obs_times):
            out.iloc[i] = float("nan")
            continue
        t0, t1 = obs_times.iloc[r - 1], obs_times.iloc[r]
        gap_min = (t1 - t0).total_seconds() / 60.0
        if gap_min > max_gap_minutes:
            out.iloc[i] = float("nan")
            continue
        frac = (t - t0).total_seconds() / (t1 - t0).total_seconds()
        out.iloc[i] = float(obs_vals[r - 1] + frac * (obs_vals[r] - obs_vals[r - 1]))
    return out


# ---------------------------------------------------------------------------
# Diagnostic helper: probe a single request to verify URL / response shape
# ---------------------------------------------------------------------------

def diagnose(
    api_id: str = "tide_hourly",
    station_code: str = "DT_0001",  # Incheon
    day: date | None = None,
    api_key: str | None = None,
) -> dict:
    """Issue one request and return raw response info for debugging.

    Useful when the data.go.kr endpoint URL is uncertain. Prints the
    request URL, HTTP status, raw response head, and parsed row count.
    """
    cfg = _load_config()
    spec = cfg["apis"][api_id]
    url = cfg["base"]["url"].rstrip("/") + spec["path"]
    day = day or date.today() - timedelta(days=2)

    # Some APIs (tide_extreme, msl) take no reqDate; others use YYYYMMDD or YYYYMM.
    fmt = spec.get("date_format")
    req_date = day.strftime(fmt) if fmt else None

    params = _build_params(
        spec,
        cfg.get("common_params", {}),
        _api_key(api_key),
        station_code,
        req_date,
    )

    resp = requests.get(url, params=params, timeout=30)
    head = resp.text[:600]
    parsed_rows: list[dict] = []
    result_code, result_msg, total = None, None, None
    try:
        payload = resp.json()
        parsed_rows = _extract_rows(payload, cfg)
        result_code, result_msg = _result_code(payload, cfg)
        total = _total_count(payload)
    except Exception:  # noqa: BLE001
        payload = None

    info = {
        "request_url": resp.url,
        "status_code": resp.status_code,
        "content_type": resp.headers.get("Content-Type"),
        "result_code": result_code,
        "result_msg": result_msg,
        "total_count": total,
        "raw_head": head,
        "rows_parsed": len(parsed_rows) if isinstance(parsed_rows, list) else 0,
        "sample_row": parsed_rows[0] if parsed_rows else None,
    }
    log.info("KHOA diagnose %s @ %s -> HTTP %s, code=%s, %d/%s rows",
             api_id, day.isoformat(), resp.status_code, result_code,
             info["rows_parsed"], total if total is not None else "?")
    return info
