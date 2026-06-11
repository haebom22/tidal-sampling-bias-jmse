"""Configuration loading utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import PROJECT_ROOT


CONFIG_DIR = PROJECT_ROOT / "config"


@dataclass
class KhoaStation:
    code: str
    name_ko: str
    name_en: str


@dataclass
class Site:
    id: str
    name_ko: str
    name_en: str
    region: str
    center: dict[str, float]
    bbox: list[float]
    tidal_range_m: float
    khoa_stations: list[KhoaStation] = field(default_factory=list)

    @property
    def lon(self) -> float:
        return self.center["lon"]

    @property
    def lat(self) -> float:
        return self.center["lat"]


def load_sites(path: Path | None = None) -> list[Site]:
    path = path or (CONFIG_DIR / "sites.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    sites: list[Site] = []
    for entry in data["sites"]:
        stations = [KhoaStation(**s) for s in entry.get("khoa_stations", [])]
        sites.append(
            Site(
                id=entry["id"],
                name_ko=entry["name_ko"],
                name_en=entry["name_en"],
                region=entry["region"],
                center=entry["center"],
                bbox=entry["bbox"],
                tidal_range_m=entry["tidal_range_m"],
                khoa_stations=stations,
            )
        )
    return sites


def load_settings(path: Path | None = None) -> dict[str, Any]:
    path = path or (CONFIG_DIR / "settings.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_path(rel: str) -> Path:
    """Resolve a path relative to the project root."""
    return PROJECT_ROOT / rel
