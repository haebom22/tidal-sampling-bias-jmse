"""FES tide-height computation using **pyfes** (AVISO native engine).

This module evaluates FES2014/FES2022 tide elevations at arbitrary
(lon, lat, time) triples. It exposes the historical
``compute_tide_heights`` signature so downstream code does not need to
change, but the backend is now ``pyfes`` (the official CNES/AVISO
package) rather than ``pyTMD``.

Why we switched to pyfes
------------------------
``pyTMD`` 3.0.x opens FES2022b NetCDF tiles through xarray with
``mask_and_scale=True``, which currently fails with
``RuntimeError: NetCDF: HDF error`` under
``xarray>=2024.11`` + ``netCDF4>=1.7`` on macOS. (The same files load
fine with ``netCDF4`` directly.)  We spent ~9 minutes per
site/year on each failed call and accumulated cascading errors.

``pyfes`` (CNES/AVISO) uses its own C++ NetCDF reader, evaluates
~17 000 timestamps per call in well under a second, and is the
reference engine for FES2022b. It also supports regional
``bbox`` subsetting at config-load time, so we only ever read the
Korean Peninsula slice (~0.6 % of each global grid).

Expected on-disk layout
-----------------------
For the bundled FES2022b extrapolated atlas::

    data/raw/fes2022b/
        ocean_tide_extrapolated/  # 34 .nc files (M2, S2, K1, O1, ...)
        load_tide/                # 34 .nc files (radial tide)

Then call ``compute_tide_heights(model_directory=Path('data/raw'),
model_name='FES2022_extrapolated')`` and we resolve the rest. Aliases
``FES2022`` and ``FES2014`` are accepted.
"""

from __future__ import annotations

import logging
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Sequence, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


_MODEL_DIR_LAYOUT = {
    # model_name -> (ocean_subdir, radial_subdir or None)
    "FES2022_extrapolated": ("fes2022b/ocean_tide_extrapolated", "fes2022b/load_tide"),
    "FES2022": ("fes2022b/ocean_tide", "fes2022b/load_tide"),
    "FES2014": ("fes2014/ocean_tide", "fes2014/load_tide"),
}


def _resolve_model_dirs(model_directory: Path, model_name: str) -> Tuple[Path, Path | None]:
    """Resolve absolute ocean / radial directories for a given model name.

    Accepts either:
      * the canonical *root* layout (``model_directory=data/raw``, with
        ``fes2022b/ocean_tide_extrapolated/*.nc`` beneath it); or
      * a *leaf* layout where ``model_directory`` already points at a
        directory full of constituent NetCDFs (legacy callers built
        before the model_name-aware resolution was added).

    The leaf form is detected by the presence of ``*.nc`` files
    directly inside ``model_directory``.
    """
    if model_name not in _MODEL_DIR_LAYOUT:
        raise ValueError(
            f"Unknown model_name={model_name!r}. Supported: "
            f"{list(_MODEL_DIR_LAYOUT)}"
        )

    root = Path(model_directory).resolve()

    # Leaf layout: model_directory itself holds the constituent .nc files.
    if root.is_dir() and any(p.suffix == ".nc" for p in root.iterdir()):
        ocean = root
        # Look for a sibling load_tide directory (best effort).
        radial_candidates = [
            root.parent / "load_tide",
            root.parent / "load_tide_extrapolated",
        ]
        radial = next((r for r in radial_candidates if r.is_dir()), None)
        return ocean, radial

    # Root layout: append the model-specific subpath.
    ocean_sub, radial_sub = _MODEL_DIR_LAYOUT[model_name]
    ocean = (root / ocean_sub).resolve()
    radial = (root / radial_sub).resolve() if radial_sub else None
    if not ocean.is_dir():
        raise FileNotFoundError(
            f"Ocean-tide directory not found: {ocean}\n"
            f"Expected NetCDF tiles under {ocean}/*.nc."
        )
    if radial is not None and not radial.is_dir():
        log.warning("Radial-tide directory not found (%s); proceeding without load tide.", radial)
        radial = None
    return ocean, radial


def _build_pyfes_yaml(ocean_dir: Path, radial_dir: Path | None) -> Path:
    """Generate the pyfes YAML config matching the on-disk NetCDF set.

    The YAML is written once per (ocean_dir, radial_dir) pair into a
    deterministic location under ``$TMPDIR`` so repeated calls reuse it.
    """
    import pyfes

    known = {c.lower(): c for c in pyfes.known_constituents()}

    def _block(d: Path | None) -> str | None:
        if d is None:
            return None
        items = []
        for f in sorted(os.listdir(d)):
            if not f.endswith(".nc"):
                continue
            stem = f[: -len(".nc")]
            # strip "_fes2022" / "_fes2014" suffix tags
            for tag in ("_fes2022", "_fes2014"):
                if stem.endswith(tag):
                    stem = stem[: -len(tag)]
                    break
            cname = known.get(stem.lower())
            if cname is None:
                log.debug("Skipping unrecognised constituent file: %s", f)
                continue
            items.append(f"      {cname}: {d / f}")
        if not items:
            return None
        return "\n".join(items)

    tide_paths = _block(ocean_dir)
    if tide_paths is None:
        raise FileNotFoundError(f"No usable constituent files in {ocean_dir}")
    radial_paths = _block(radial_dir) if radial_dir is not None else None

    yaml_text = ["engine: darwin", "tide:", "  cartesian:",
                 "    amplitude: amplitude", "    latitude: lat",
                 "    longitude: lon", "    phase: phase", "    paths:",
                 tide_paths]
    if radial_paths is not None:
        yaml_text += ["radial:", "  cartesian:",
                      "    amplitude: amplitude", "    latitude: lat",
                      "    longitude: lon", "    phase: phase", "    paths:",
                      radial_paths]
    yaml_str = "\n".join(yaml_text) + "\n"

    cache_dir = Path(tempfile.gettempdir()) / "tidalflat-pyfes-configs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Filename keyed on absolute ocean dir → stable across runs.
    tag = str(ocean_dir).replace(os.sep, "_").lstrip("_")
    cfg = cache_dir / f"{tag}.yaml"
    if not cfg.exists() or cfg.read_text() != yaml_str:
        cfg.write_text(yaml_str)
        log.info("Wrote pyfes config: %s", cfg)
    return cfg


@lru_cache(maxsize=8)
def _load_config_cached(
    yaml_path: str,
    bbox: Tuple[float, float, float, float] | None,
):
    """Memoised wrapper around ``pyfes.config.load`` for repeat queries.

    The cache key is ``(yaml_path, bbox)``. Each loaded ``Configuration``
    keeps the global (or bbox-subset) tide constituent grids in memory,
    so subsequent ``pyfes.evaluate_tide`` calls are sub-second even for
    tens of thousands of timestamps.

    Callers should pass a *stable* (e.g. national) ``bbox`` so the grids
    load exactly once per process. Repeatedly opening/slicing the FES
    HDF5/NetCDF atlases (a fresh ``bbox`` every tile) is what triggers
    the intermittent ``RuntimeError: NetCDF: HDF error``; a single load
    sidesteps it. A short retry guards the first (transient) load.
    """
    import time

    import pyfes
    bbox_arg = tuple(bbox) if bbox is not None else None
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return pyfes.config.load(yaml_path, bbox=bbox_arg)
        except RuntimeError as exc:  # netCDF/HDF transient read failures
            last_exc = exc
            log.warning(
                "pyfes.config.load HDF error (attempt %d/3): %s — retrying",
                attempt + 1, exc,
            )
            time.sleep(1.5 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def compute_tide_heights(
    lon: float | Sequence[float],
    lat: float | Sequence[float],
    times: pd.DatetimeIndex | Sequence[pd.Timestamp],
    model_directory: Path,
    model_name: str = "FES2022_extrapolated",
    method: str = "linear",          # accepted for API compatibility; pyfes uses spline by default
    extrapolate: bool = True,        # ditto — handled via *_extrapolated atlas
    bounds: Sequence[float] | None = None,
    crop: bool | None = None,
    include_load_tide: bool = True,
) -> np.ndarray:
    """Compute tide heights (metres) at the given location(s) and time(s).

    Parameters
    ----------
    lon, lat
        Scalar coordinates (drift mode at a single point) or arrays of
        equal length matching ``times``.
    times
        Timezone-aware (UTC) timestamps.
    model_directory
        Root directory containing ``fes2022b/`` (or ``fes2014/``).
    model_name
        ``"FES2022_extrapolated"`` (default), ``"FES2022"``, or
        ``"FES2014"``.
    method, extrapolate
        Kept for backwards compatibility with the pyTMD call site;
        pyfes uses the spline (Darwin) inference internally and the
        choice of ``ocean_tide_extrapolated`` already controls the
        extrapolated grid.
    bounds
        Optional ``[lon_min, lat_min, lon_max, lat_max]``. When given,
        pyfes only reads that geographic subset, slashing memory and
        load time (~10 s for the Korean Peninsula vs ~30 s globally).
    crop
        Reserved for API compatibility. ``bounds`` already triggers
        regional loading; this flag is ignored.
    include_load_tide
        If True and the load-tide atlas is present, add it to the
        elevation (geocentric tide). Default True matches FES2022b
        recommended use for altimetry/coastal applications.

    Returns
    -------
    ndarray
        Tide heights in metres, same length as ``times``. NaN where
        pyfes flagged the point as unevaluable (outside the grid,
        masked land cell, etc.).
    """
    try:
        import pyfes  # noqa: F401  (presence check)
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "pyfes is required: `pip install pyfes`."
        ) from exc
    import pyfes

    del crop  # accepted but ignored under pyfes backend

    # ---- normalise inputs ----------------------------------------------------
    times = pd.to_datetime(times, utc=True)
    # pyfes expects tz-naive datetime64 (UTC assumed); strip tz to avoid
    # numpy's "no explicit representation of timezones" UserWarning.
    times_np = np.asarray(
        times.tz_convert(None).to_pydatetime(), dtype="datetime64[us]"
    )

    lon_arr = np.atleast_1d(np.asarray(lon, dtype=float))
    lat_arr = np.atleast_1d(np.asarray(lat, dtype=float))
    if lon_arr.size == 1 and lat_arr.size == 1:
        lon_arr = np.full(len(times_np), float(lon_arr[0]))
        lat_arr = np.full(len(times_np), float(lat_arr[0]))
    elif lon_arr.size != lat_arr.size or lon_arr.size != len(times_np):
        raise ValueError(
            "lon/lat must be scalar or have the same length as `times`."
        )

    # ---- resolve / load the pyfes config -------------------------------------
    ocean_dir, radial_dir = _resolve_model_dirs(Path(model_directory), model_name)
    yaml_path = _build_pyfes_yaml(ocean_dir, radial_dir)
    bbox_t: Tuple[float, float, float, float] | None = (
        (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
        if bounds is not None else None
    )
    log.info(
        "pyfes tide computation: %d samples, model=%s, ocean=%s, "
        "bounds=%s, include_load=%s",
        len(times_np), model_name, ocean_dir.name, bbox_t, include_load_tide,
    )
    cfg = _load_config_cached(str(yaml_path), bbox_t)

    # ---- evaluate ------------------------------------------------------------
    tide, lp, flags = pyfes.evaluate_tide(
        cfg.models["tide"], times_np, lon_arr, lat_arr, settings=cfg.settings
    )
    elev = np.asarray(tide, dtype=float) + np.asarray(lp, dtype=float)

    if include_load_tide and "radial" in cfg.models:
        load_tide, load_lp, _ = pyfes.evaluate_tide(
            cfg.models["radial"], times_np, lon_arr, lat_arr, settings=cfg.settings
        )
        elev = elev + np.asarray(load_tide, dtype=float) + np.asarray(load_lp, dtype=float)

    # pyfes returns centimetres; convert to metres.
    elev = elev / 100.0

    # pyfes uses sentinel flags (e.g. 1 == valid, 2 == infer). For
    # robust QA, mask any non-finite results to NaN.
    elev = np.where(np.isfinite(elev), elev, np.nan)
    return elev


def synthetic_reference_series(
    lon: float,
    lat: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    sampling_minutes: int,
    model_directory: Path,
    model_name: str = "FES2022_extrapolated",
    bounds: Sequence[float] | None = None,
) -> pd.DataFrame:
    """Dense synthetic tide series at a fixed location.

    Used to characterise the full astronomical tide envelope at each
    site (the "ground-truth" tide distribution that satellite samples
    are compared against).
    """
    # Accept both tz-naive and tz-aware inputs. Newer pandas rejects
    # ``pd.Timestamp(value, tz=...)`` when value already carries tzinfo.
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    times = pd.date_range(start, end, freq=f"{sampling_minutes}min", tz="UTC")
    heights = compute_tide_heights(
        lon=lon, lat=lat, times=times,
        model_directory=model_directory, model_name=model_name,
        bounds=bounds,
    )
    return pd.DataFrame({"datetime_utc": times, "tide_m": heights})
