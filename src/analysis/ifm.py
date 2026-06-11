"""Inundation Frequency Method (IFM) DEM synthesis.

Reuses the per-pixel ``inundation_frequency`` band already exported by the
manuscript-2 waterline pipeline (``src.gee.dem.build_dem_gee`` → band 5 of
``data/outputs/dem/{site}_v*.tif``). ICESat-2 ATL06-SR ground segments,
already cached in ``data/processed/{site}_icesat2_exposed.parquet``, serve
as the prior elevation control points for the frequency → elevation
regression (Xu 2022; Zheng 2024; Xin 2025; Li 2026).

Output DEM is in the same vertical reference (KHOA chart datum, same as the
input waterline DEM) so the resulting IFM-DEM is directly comparable to
the V3-KHOA waterline DEM produced by ``run_v3_khoa_variant.py``.

Three regression models are supported:

- ``slm``  : Simple linear model       z = a + b · f           (Xu 2022)
- ``poly3``: 3rd-order polynomial      z = Σ_i c_i · f^i       (Li 2026)
- ``rf``   : Random Forest             z = RF(f, [optional: y_landward])  (Zhang 2024)

For Phase 1 the input feature is the inundation frequency only.  Phase 2
will add the landward-distance feature for the FDJR variant.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import rowcol
from shapely import wkb

log = logging.getLogger(__name__)

# Band indices in the manuscript-2 waterline DEM GeoTIFF.
BAND_DEM = 1
BAND_FREQ = 5

DEFAULT_FREQ_RANGE = (0.03, 0.97)
DEFAULT_TEST_FRACTION = 0.20
DEFAULT_RANDOM_STATE = 42
DEFAULT_SIGMA_CLIP = 2.0  # tighter than 3σ once upland contamination is removed
DEFAULT_ELEV_PERCENTILES = (5.0, 95.0)
DEFAULT_ELEV_BUFFER_M = 2.0


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class IFMFitResult:
    """Metrics + fitted-model artefacts for one (site, model) pair."""

    site_id: str
    model: str
    n_train: int
    n_test: int
    train_rmse_m: float
    test_rmse_m: float
    train_mae_m: float
    test_mae_m: float
    train_bias_m: float
    test_bias_m: float
    train_r2: float
    test_r2: float
    datum_offset_m: float
    freq_range: tuple[float, float]
    coefficients: list[float] | None  # SLM / poly3 parameter vector
    elevation_range_m: tuple[float, float]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["freq_range"] = list(d["freq_range"])
        d["elevation_range_m"] = list(d["elevation_range_m"])
        return d


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_waterline_dem(
    dem_path: Path,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return (dem_band1, freq_band5, raster_profile) for an existing waterline DEM."""
    with rasterio.open(dem_path) as src:
        dem = src.read(BAND_DEM, masked=True).filled(np.nan)
        freq = src.read(BAND_FREQ, masked=True).filled(np.nan)
        profile = src.profile.copy()
        profile["crs"] = src.crs
        profile["transform"] = src.transform
    return dem, freq, profile


def load_icesat2_points(icesat2_path: Path) -> gpd.GeoDataFrame:
    """Load the cached ICESat-2 exposed segments as a GeoDataFrame in EPSG:4326."""
    pdf = pd.read_parquet(icesat2_path)
    if pdf.empty:
        raise ValueError(f"empty ICESat-2 cache: {icesat2_path}")
    if "geometry" not in pdf.columns:
        raise KeyError("expected 'geometry' column in ICESat-2 cache")
    geom = pdf["geometry"].apply(lambda g: wkb.loads(g) if isinstance(g, (bytes, bytearray)) else g)
    return gpd.GeoDataFrame(pdf, geometry=geom, crs="EPSG:4326")


def sample_band_at_points(
    raster_path: Path,
    points: gpd.GeoDataFrame,
    band: int,
) -> np.ndarray:
    """Sample a single raster band at point locations (no interpolation)."""
    with rasterio.open(raster_path) as src:
        pts = points.to_crs(src.crs)
        xs = pts.geometry.x.to_numpy()
        ys = pts.geometry.y.to_numpy()
        rows, cols = rowcol(src.transform, xs, ys)
        rows = np.asarray(rows, dtype=np.int64)
        cols = np.asarray(cols, dtype=np.int64)
        h, w = src.height, src.width
        valid = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
        out = np.full(len(xs), np.nan)
        if valid.any():
            data = src.read(band, masked=True)
            vals = data[rows[valid], cols[valid]]
            arr = np.asarray(vals.filled(np.nan), dtype=float)
            out[valid] = arr
    return out


# ---------------------------------------------------------------------------
# Calibration sample preparation
# ---------------------------------------------------------------------------

def _waterline_intertidal_band(
    dem_band: np.ndarray,
    percentiles: tuple[float, float] = DEFAULT_ELEV_PERCENTILES,
    buffer_m: float = DEFAULT_ELEV_BUFFER_M,
) -> tuple[float, float]:
    """Return the ``(elev_min, elev_max)`` band that defines the intertidal zone.

    Computed as ``[p5 - buffer, p95 + buffer]`` of the waterline DEM
    (manuscript-2 ``validate_icesat2.py`` convention). This bounds the
    true intertidal elevation regardless of vertical datum, so it can
    be used both before and after the ``datum_offset`` shift to
    discard upland ICESat-2 returns (forests, buildings, etc.).
    """
    finite = dem_band[np.isfinite(dem_band)]
    if finite.size == 0:
        raise ValueError("waterline DEM has no finite pixels")
    lo, hi = np.percentile(finite, list(percentiles))
    return float(lo - buffer_m), float(hi + buffer_m)


def prepare_calibration_sample(
    waterline_dem_path: Path,
    icesat2_path: Path,
    freq_range: tuple[float, float] = DEFAULT_FREQ_RANGE,
    sigma_clip: float = DEFAULT_SIGMA_CLIP,
    height_col: str = "h_mean",
    elev_percentiles: tuple[float, float] = DEFAULT_ELEV_PERCENTILES,
    elev_buffer_m: float = DEFAULT_ELEV_BUFFER_M,
) -> tuple[pd.DataFrame, float]:
    """Match ICESat-2 points to the waterline DEM's frequency band.

    Filter pipeline (in order):

      1. Drop ICESat-2 points outside the raster footprint, or with
         NaN frequency / waterline DEM.
      2. Keep frequencies inside ``freq_range`` (intertidal window).
      3. Estimate datum offset = ``median(h_mean - waterline_dem)``
         on the subset and shift to ``h_chart``.
      4. Drop ICESat-2 points whose ``h_chart`` falls outside the
         waterline DEM's intertidal elevation band ``[p5 − buffer,
         p95 + buffer]``. This removes upland vegetation/buildings
         that ATL06-SR keeps but that have nothing to do with the
         intertidal surface (e.g. h_mean ≫ 30 m over Korean coasts).
      5. ``sigma_clip``-σ clip on the residual ``h_chart -
         waterline_dem``, computed *after* the elevation-band cut so
         σ reflects the intertidal noise rather than upland scatter.

    Returns
    -------
    sample
        DataFrame ``[lon, lat, h_mean, freq, waterline_dem, h_chart]``.
    datum_offset_m
        The applied ``h_mean → h_chart`` offset (Korean WGS84 ↔ KHOA
        chart datum is typically ~+25 m).
    """
    points = load_icesat2_points(icesat2_path)
    freq = sample_band_at_points(waterline_dem_path, points, band=BAND_FREQ)
    dem = sample_band_at_points(waterline_dem_path, points, band=BAND_DEM)
    h = points[height_col].to_numpy(dtype=float)
    lon = points.geometry.x.to_numpy()
    lat = points.geometry.y.to_numpy()

    sample = pd.DataFrame({
        "lon": lon,
        "lat": lat,
        "h_mean": h,
        "freq": freq,
        "waterline_dem": dem,
    })

    n0 = len(sample)

    # (1) Drop NaN rows.
    sample = sample.dropna(subset=["h_mean", "freq", "waterline_dem"])
    log.info("  drop NaN:               %d / %d points", len(sample), n0)
    if sample.empty:
        raise ValueError("no ICESat-2 points with both freq and waterline DEM values")

    # (2) Intertidal frequency window.
    f_lo, f_hi = freq_range
    sample = sample.loc[sample["freq"].between(f_lo, f_hi)].copy()
    log.info("  freq window [%.2f,%.2f]:  %d points", f_lo, f_hi, len(sample))
    if sample.empty:
        raise ValueError("no ICESat-2 points in intertidal frequency window")

    # (3) Datum offset (using current intertidal subset; iteratively
    #     refined below once outliers are dropped).
    diffs = sample["h_mean"] - sample["waterline_dem"]
    datum_offset = float(np.median(diffs))
    sample["h_chart"] = sample["h_mean"] - datum_offset
    log.info("  datum offset (init):    %+0.3f m", datum_offset)

    # (4) Elevation-band cut (manuscript-2 convention).
    dem_band, _, _ = load_waterline_dem(waterline_dem_path)
    elev_lo, elev_hi = _waterline_intertidal_band(
        dem_band, percentiles=elev_percentiles, buffer_m=elev_buffer_m,
    )
    keep = sample["h_chart"].between(elev_lo, elev_hi)
    log.info(
        "  elev band [%+0.2f,%+0.2f]: %d / %d points",
        elev_lo, elev_hi, int(keep.sum()), len(sample),
    )
    sample = sample.loc[keep].copy()
    if sample.empty:
        raise ValueError("no ICESat-2 points inside waterline DEM elevation band")

    # (5) Refine datum offset on the clean subset and re-shift.
    diffs = sample["h_mean"] - sample["waterline_dem"]
    refined_offset = float(np.median(diffs))
    sample["h_chart"] = sample["h_mean"] - refined_offset
    log.info("  datum offset (refined): %+0.3f m", refined_offset)

    # (6) σ-clip on intertidal residuals.
    residual = sample["h_chart"] - sample["waterline_dem"]
    std = float(np.std(residual))
    keep = residual.abs() <= sigma_clip * std
    log.info(
        "  σ-clip (%.1fσ, σ=%.3f m):  %d / %d points",
        sigma_clip, std, int(keep.sum()), len(sample),
    )
    sample = sample.loc[keep].copy()

    log.info(
        "  calibration sample ready: n=%d, h_chart=[%.2f, %.2f] m",
        len(sample), sample["h_chart"].min(), sample["h_chart"].max(),
    )
    return sample, refined_offset


# ---------------------------------------------------------------------------
# Regression model adapters
# ---------------------------------------------------------------------------

class _BaseModel:
    name: str = "base"

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        raise NotImplementedError

    def predict(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    @property
    def coefficients(self) -> list[float] | None:
        return None


class _SLM(_BaseModel):
    name = "slm"

    def __init__(self) -> None:
        self.b = 0.0
        self.a = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        f = X[:, 0]
        b, a = np.polyfit(f, y, 1)
        self.b = float(b)
        self.a = float(a)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.a + self.b * X[:, 0]

    @property
    def coefficients(self) -> list[float]:
        return [self.a, self.b]


class _Poly3(_BaseModel):
    name = "poly3"

    def __init__(self) -> None:
        self.coef = np.zeros(4)  # c0 + c1·f + c2·f² + c3·f³

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        f = X[:, 0]
        c3, c2, c1, c0 = np.polyfit(f, y, 3)
        self.coef = np.array([c0, c1, c2, c3], dtype=float)

    def predict(self, X: np.ndarray) -> np.ndarray:
        f = X[:, 0]
        c0, c1, c2, c3 = self.coef
        return c0 + c1 * f + c2 * f * f + c3 * f * f * f

    @property
    def coefficients(self) -> list[float]:
        return [float(c) for c in self.coef]


class _RF(_BaseModel):
    name = "rf"

    def __init__(self, n_estimators: int = 200, random_state: int = DEFAULT_RANDOM_STATE):
        from sklearn.ensemble import RandomForestRegressor

        self._model = RandomForestRegressor(
            n_estimators=n_estimators,
            min_samples_leaf=10,
            n_jobs=-1,
            random_state=random_state,
        )

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self._model.fit(X, y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self._model.predict(X)


def _make_model(name: str) -> _BaseModel:
    if name == "slm":
        return _SLM()
    if name == "poly3":
        return _Poly3()
    if name == "rf":
        return _RF()
    raise ValueError(f"unknown IFM model: {name!r}")


# ---------------------------------------------------------------------------
# Train + apply
# ---------------------------------------------------------------------------

def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float, float]:
    diff = y_pred - y_true
    rmse = float(np.sqrt(np.mean(diff * diff)))
    mae = float(np.mean(np.abs(diff)))
    bias = float(np.mean(diff))
    ss_res = float(np.sum(diff * diff))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return rmse, mae, bias, r2


def fit_ifm(
    sample: pd.DataFrame,
    model_name: str,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> tuple[_BaseModel, IFMFitResult]:
    """Fit one regression model on the calibration sample.

    The sample is randomly split into (train, test) using ``random_state``.
    Returns the fitted model and a :class:`IFMFitResult` with both
    in-sample and held-out test metrics.
    """
    rng = np.random.default_rng(random_state)
    idx = np.arange(len(sample))
    rng.shuffle(idx)
    n_test = int(round(len(sample) * test_fraction))
    test_idx = idx[:n_test]
    train_idx = idx[n_test:]
    train = sample.iloc[train_idx]
    test = sample.iloc[test_idx]

    X_train = train["freq"].to_numpy().reshape(-1, 1)
    y_train = train["h_chart"].to_numpy()
    X_test = test["freq"].to_numpy().reshape(-1, 1)
    y_test = test["h_chart"].to_numpy()

    model = _make_model(model_name)
    model.fit(X_train, y_train)
    y_train_pred = model.predict(X_train)
    y_test_pred = model.predict(X_test)

    train_rmse, train_mae, train_bias, train_r2 = _metrics(y_train, y_train_pred)
    test_rmse, test_mae, test_bias, test_r2 = _metrics(y_test, y_test_pred)

    elev_range = (float(sample["h_chart"].min()), float(sample["h_chart"].max()))
    fit_result = IFMFitResult(
        site_id="",  # set by caller
        model=model_name,
        n_train=len(train),
        n_test=len(test),
        train_rmse_m=train_rmse,
        test_rmse_m=test_rmse,
        train_mae_m=train_mae,
        test_mae_m=test_mae,
        train_bias_m=train_bias,
        test_bias_m=test_bias,
        train_r2=train_r2,
        test_r2=test_r2,
        datum_offset_m=0.0,  # filled by build_ifm_dem
        freq_range=DEFAULT_FREQ_RANGE,
        coefficients=model.coefficients,
        elevation_range_m=elev_range,
    )
    log.info(
        "  %-6s | train n=%d RMSE=%.3f R²=%.3f | test n=%d RMSE=%.3f R²=%.3f",
        model_name, len(train), train_rmse, train_r2,
        len(test), test_rmse, test_r2,
    )
    return model, fit_result


def apply_model_to_raster(
    model: _BaseModel,
    freq_band: np.ndarray,
    freq_range: tuple[float, float] = DEFAULT_FREQ_RANGE,
) -> np.ndarray:
    """Apply a fitted IFM model to the frequency band and return an elevation raster."""
    out = np.full(freq_band.shape, np.nan, dtype=np.float32)
    f_lo, f_hi = freq_range
    mask = np.isfinite(freq_band) & (freq_band >= f_lo) & (freq_band <= f_hi)
    if not mask.any():
        return out
    f_flat = freq_band[mask].reshape(-1, 1)
    z_flat = model.predict(f_flat)
    out[mask] = z_flat.astype(np.float32)
    return out


def write_ifm_dem(
    out_path: Path,
    ifm_dem: np.ndarray,
    freq_band: np.ndarray,
    profile: dict,
    nodata: float = -9999.0,
) -> Path:
    """Write the IFM-DEM as a 2-band GeoTIFF (band1=ifm_dem, band2=freq)."""
    out_profile = profile.copy()
    out_profile.update(
        count=2,
        dtype="float32",
        nodata=nodata,
        compress="deflate",
        BIGTIFF="IF_SAFER",
    )
    ifm = np.where(np.isfinite(ifm_dem), ifm_dem, nodata).astype(np.float32)
    freq = np.where(np.isfinite(freq_band), freq_band, nodata).astype(np.float32)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(ifm, 1)
        dst.write(freq, 2)
        dst.set_band_description(1, "ifm_dem_m")
        dst.set_band_description(2, "inundation_frequency")
    return out_path


def build_ifm_dem(
    waterline_dem_path: Path,
    icesat2_path: Path,
    out_dir: Path,
    site_id: str,
    models: Sequence[str] = ("slm", "poly3", "rf"),
    freq_range: tuple[float, float] = DEFAULT_FREQ_RANGE,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    random_state: int = DEFAULT_RANDOM_STATE,
    sigma_clip: float = DEFAULT_SIGMA_CLIP,
    output_suffix: str = "ifm",
) -> dict:
    """End-to-end IFM DEM build for a single site.

    Parameters
    ----------
    output_suffix
        Substring placed between the site id and the model name in the
        per-model GeoTIFF/summary filenames. The default ``"ifm"`` keeps
        backward compatibility (``garorim_ifm_rf.tif``); use e.g.
        ``"ifm_s1"`` for the S1-augmented run so its rasters do not
        overwrite the optical-only run.

    Returns
    -------
    dict
        Per-model metrics, datum offset, output paths.
    """
    log.info("=" * 72)
    log.info("[IFM] %s — waterline=%s, icesat2=%s, suffix=%s",
             site_id, waterline_dem_path.name, icesat2_path.name, output_suffix)

    sample, datum_offset = prepare_calibration_sample(
        waterline_dem_path, icesat2_path,
        freq_range=freq_range, sigma_clip=sigma_clip,
    )

    dem_b1, freq_b5, profile = load_waterline_dem(waterline_dem_path)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {
        "site_id": site_id,
        "input_waterline_tif": str(waterline_dem_path),
        "input_icesat2_parquet": str(icesat2_path),
        "datum_offset_m": datum_offset,
        "n_calibration_points": int(len(sample)),
        "freq_range": list(freq_range),
        "models": {},
    }

    for name in models:
        log.info("[IFM] %s | fitting %s", site_id, name)
        model, fit_res = fit_ifm(
            sample, model_name=name,
            test_fraction=test_fraction, random_state=random_state,
        )
        fit_res.site_id = site_id
        fit_res.datum_offset_m = datum_offset
        fit_res.freq_range = freq_range

        ifm = apply_model_to_raster(model, freq_b5, freq_range=freq_range)
        out_tif = out_dir / f"{site_id}_{output_suffix}_{name}.tif"
        write_ifm_dem(out_tif, ifm, freq_b5, profile)
        log.info("  wrote DEM → %s  (%d valid pixels)",
                 out_tif, int(np.isfinite(ifm).sum()))

        summary["models"][name] = {
            **fit_res.to_dict(),
            "output_tif": str(out_tif),
        }

    json_path = out_dir / f"{site_id}_{output_suffix}_summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    log.info("[IFM] %s — summary → %s", site_id, json_path)

    return summary


__all__ = [
    "BAND_DEM",
    "BAND_FREQ",
    "DEFAULT_FREQ_RANGE",
    "IFMFitResult",
    "build_ifm_dem",
    "fit_ifm",
    "load_icesat2_points",
    "load_waterline_dem",
    "prepare_calibration_sample",
    "sample_band_at_points",
    "write_ifm_dem",
    "apply_model_to_raster",
]
