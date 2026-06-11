"""Parquet IO that is robust against the pyarrow + rasterio file-system clash.

Importing ``rasterio`` registers a GDAL handler for the ``file://`` URI scheme
that conflicts with pyarrow ≥24's ``LocalFileSystem`` factory registration.
After rasterio is imported, ``pandas.DataFrame.to_parquet`` (which internally
constructs a new ``pyarrow.fs.LocalFileSystem``) fails with::

    pyarrow.lib.ArrowKeyError: Attempted to register factory for scheme
    'file' but that scheme is already registered.

This module provides two helpers that try pyarrow first and transparently
fall back to fastparquet on that specific error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

_ARROW_FACTORY_ERR = "already registered"


def to_parquet(df: pd.DataFrame, path: Any, **kwargs: Any) -> None:
    """``DataFrame.to_parquet`` with automatic fastparquet fallback."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(p, **kwargs)
    except Exception as exc:  # noqa: BLE001
        if _ARROW_FACTORY_ERR not in str(exc):
            raise
        kwargs.pop("engine", None)
        df.to_parquet(p, engine="fastparquet", **kwargs)


def read_parquet(path: Any, **kwargs: Any) -> pd.DataFrame:
    """``pd.read_parquet`` with automatic fastparquet fallback."""
    try:
        return pd.read_parquet(path, **kwargs)
    except Exception as exc:  # noqa: BLE001
        if _ARROW_FACTORY_ERR not in str(exc):
            raise
        kwargs.pop("engine", None)
        return pd.read_parquet(path, engine="fastparquet", **kwargs)
