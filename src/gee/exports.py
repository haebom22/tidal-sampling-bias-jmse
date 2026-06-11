"""Local GeoTIFF export helpers for GEE images.

Two export paths are provided:

1. ``export_image_to_local`` — uses ``geemap.ee_export_image``
   (``getDownloadURL``, 48 MB cap) for moderate-size rasters. For
   larger rasters, increase the scale or use ``export_image_to_drive``.

2. ``export_image_to_drive`` — asynchronous Drive export with no
   practical size limit (the GEE export system splits automatically).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import ee

log = logging.getLogger(__name__)

DEFAULT_CRS = "EPSG:32652"  # UTM 52N — covers both Garorim and Suncheon


@dataclass
class ExportResult:
    out_path: Path
    crs: str
    scale_m: float
    n_bytes: int

    @property
    def ok(self) -> bool:
        return self.out_path.exists() and self.n_bytes > 0


def export_image_to_local(
    image: ee.Image,
    region: ee.Geometry,
    scale_m: float,
    out_path: Path,
    crs: str = DEFAULT_CRS,
    overwrite: bool = False,
    file_per_band: bool = False,
    auto_rescale: bool = True,
    max_rescale_factor: int = 8,
) -> ExportResult:
    """Synchronously export an EE image to a local GeoTIFF.

    Uses ``geemap.ee_export_image`` (backed by ``getDownloadURL``).
    The 48 MB per-request cap applies; the function automatically
    catches the "Total request size … must be less than or equal to
    50331648 bytes" error and re-tries at coarser ``scale_m``
    (doubling each time, up to ``max_rescale_factor``) so that small-
    bbox calls succeed silently and large-bbox calls degrade gracefully
    rather than burning quota on doomed retries.

    Empty results (e.g. GEE 5-minute computation timeouts) are also
    treated as "needs rescale": the same call at the same scale almost
    never recovers, so we move directly to the next coarser scale
    instead of burning another 5-10 minutes per retry.

    For unconditional full-resolution export use ``export_image_to_drive``.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not overwrite:
        log.info("Cached export: %s", out_path)
        return ExportResult(
            out_path=out_path,
            crs=crs,
            scale_m=float(scale_m),
            n_bytes=out_path.stat().st_size,
        )

    try:
        import geemap
    except ImportError as exc:
        raise RuntimeError(
            "geemap is required for local image export. "
            "Install it with `pip install geemap`."
        ) from exc

    import contextlib
    import io

    def _is_size_error(text: str) -> bool:
        t = text.lower()
        return (
            "must be less than" in t
            or "total request size" in t
            or "user memory limit exceeded" in t
        )

    factor = 1
    current_scale = float(scale_m)
    n_bytes = 0
    while True:
        # One attempt per scale. The GEE sync-download path has a hard
        # ~5-minute compute budget; if it returns empty, retrying at
        # the same scale almost never succeeds within that budget, so
        # we move straight to the next coarser scale.
        if out_path.exists():
            out_path.unlink()
        buf = io.StringIO()
        attempt_failed = False
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                geemap.ee_export_image(
                    image,
                    filename=str(out_path),
                    scale=current_scale,
                    region=region,
                    crs=crs,
                    file_per_band=file_per_band,
                )
        except Exception as exc:  # noqa: BLE001
            attempt_failed = True
            msg = f"{exc} | {buf.getvalue()}"
            log.warning(
                "Export at scale=%.0fm raised: %s",
                current_scale, msg.strip(),
            )

        output = buf.getvalue()
        if _is_size_error(output):
            log.warning(
                "Export scale=%.0fm exceeds 50 MB sync limit: %s",
                current_scale,
                output.strip().splitlines()[-1] if output.strip() else "size limit",
            )

        n_bytes = out_path.stat().st_size if out_path.exists() else 0
        if n_bytes > 0:
            break

        # Empty result (size error, compute timeout, or other failure).
        # Try the next coarser scale.
        if not auto_rescale:
            log.warning(
                "Empty export at scale=%.0fm (auto_rescale=False) — giving up on %s.",
                current_scale, out_path.name,
            )
            break
        factor *= 2
        if factor > max_rescale_factor:
            log.warning(
                "Rescale exhausted (factor x%d, scale=%.0fm) — giving up on %s.",
                factor // 2, current_scale, out_path.name,
            )
            break
        current_scale = float(scale_m) * factor
        log.warning(
            "Empty result at scale=%.0fm; retrying at coarser scale=%.0fm (factor x%d).",
            float(scale_m) * (factor // 2), current_scale, factor,
        )

    if n_bytes == 0:
        log.warning("Empty export, no raster written: %s", out_path)
    return ExportResult(
        out_path=out_path, crs=crs, scale_m=float(current_scale), n_bytes=n_bytes,
    )


def export_image_to_drive(
    image: ee.Image,
    region: ee.Geometry,
    scale_m: float,
    description: str,
    folder: str = "tidalflat_dem",
    crs: str = DEFAULT_CRS,
) -> ee.batch.Task:
    """Submit an asynchronous Drive export (for larger rasters).

    Use this when the bbox / band count exceeds the 33 MB
    synchronous download cap.
    """
    task = ee.batch.Export.image.toDrive(
        image=image,
        description=description,
        folder=folder,
        fileNamePrefix=description,
        region=region,
        scale=float(scale_m),
        crs=crs,
        maxPixels=int(1e10),
    )
    task.start()
    log.info("Submitted Drive export task: %s (id=%s)", description, task.id)
    return task


def wait_for_task(task: ee.batch.Task, poll_interval_s: int = 30) -> str:
    """Block until a GEE export task finishes. Returns final status."""
    import time

    while True:
        status = task.status()
        state = status.get("state", "UNKNOWN")
        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            if state == "FAILED":
                log.error("Task %s FAILED: %s", task.id, status.get("error_message"))
            else:
                log.info("Task %s %s", task.id, state)
            return state
        log.info("Task %s state=%s, waiting %ds...", task.id, state, poll_interval_s)
        time.sleep(poll_interval_s)
