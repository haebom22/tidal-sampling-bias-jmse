"""Generate the study area map (Figure 1).

Shows the five study sites along the western/southern Korean coast,
their associated KHOA tide-gauge stations, and approximate tidal
ranges.  Coastline rendered with Cartopy.
"""

from __future__ import annotations

from pathlib import Path

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

from src.config import load_sites

OUT_PATH = Path("manuscript/figures/fig1_study_area.png")


# KHOA station coordinates (lon, lat)
KHOA_COORDS = {
    "DT_0001": (126.5926, 37.4516),   # Incheon
    "DT_0067": (126.1300, 36.6750),   # Anheung
    "DT_0018": (126.5630, 35.9750),   # Gunsan (외항)
    "DT_0003": (126.1090, 35.4500),   # Yeonggwang (백수읍 부근)
    "DT_0016": (127.7665, 34.7475),   # Yeosu
}

SITE_COLORS = {
    "ganghwa":   "#1f77b4",
    "garorim":   "#2ca02c",
    "gomso":     "#9467bd",
    "hampyeong": "#d62728",
    "suncheon":  "#ff7f0e",
}


def main() -> None:
    sites = load_sites()

    fig = plt.figure(figsize=(11, 9))
    proj = ccrs.PlateCarree()
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    ax.set_extent([124.4, 130.4, 33.5, 39.2], crs=proj)

    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#e6f1fb")
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#f5efe2",
                   edgecolor="#7c7c7c", linewidth=0.4)
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), linewidth=0.7,
                   edgecolor="#5b5b5b")
    ax.add_feature(cfeature.BORDERS.with_scale("10m"), linewidth=0.5,
                   edgecolor="#9c9c9c", linestyle=":")

    # Gridlines
    gl = ax.gridlines(draw_labels=True, linewidth=0.4, color="gray",
                      alpha=0.3, linestyle=":")
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 9}
    gl.ylabel_style = {"size": 9}

    # Plot sites
    for site in sites:
        color = SITE_COLORS.get(site.id, "black")
        lon0, lat0, lon1, lat1 = site.bbox
        ax.add_patch(plt.Rectangle((lon0, lat0), lon1 - lon0, lat1 - lat0,
                                    facecolor=color, edgecolor="black",
                                    linewidth=0.6, alpha=0.55, transform=proj))
        cx = 0.5 * (lon0 + lon1)
        cy = 0.5 * (lat0 + lat1)
        ax.plot(cx, cy, marker="o", color=color, markeredgecolor="black",
                markersize=9, markeredgewidth=0.6, transform=proj)
        # Site label
        ax.annotate(
            f"{site.name_en}\n(MSR ≈ {site.tidal_range_m:.0f} m)",
            xy=(cx, cy), xytext=(cx + 0.45, cy + 0.2),
            fontsize=10, fontweight="bold",
            color="black", transform=proj,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=color, linewidth=1.0, alpha=0.92),
            arrowprops=dict(arrowstyle="-", color=color, linewidth=0.7),
        )
        # KHOA station marker
        station = site.khoa_stations[0]
        if station.code in KHOA_COORDS:
            slon, slat = KHOA_COORDS[station.code]
            ax.plot(slon, slat, marker="^", color="black",
                    markersize=8, markeredgecolor="white",
                    markeredgewidth=0.6, transform=proj)
            ax.annotate(f"{station.name_en}", xy=(slon, slat),
                        xytext=(slon + 0.05, slat - 0.18),
                        fontsize=8, color="#222", transform=proj,
                        style="italic")

    # Title and labels
    ax.set_title(
        "Study area: five macrotidal sites along the western and southern Korean coast",
        fontsize=12, pad=10,
    )

    # Legend
    from matplotlib.lines import Line2D
    legend_handles = [
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#1f77b4",
               markeredgecolor="black", markersize=10, label="Tidal-flat study site (bbox)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#1f77b4",
               markeredgecolor="black", markersize=10, label="Site centroid"),
        Line2D([0], [0], marker="^", color="black",
               markeredgecolor="white", markersize=10, label="KHOA tide-gauge station"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", fontsize=9,
              frameon=True, facecolor="white", edgecolor="black")

    # North arrow (MDPI requires a north arrow on maps)
    ax.annotate("", xy=(0.945, 0.95), xytext=(0.945, 0.87),
                xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color="black", linewidth=1.8))
    ax.text(0.945, 0.965, "N", transform=ax.transAxes, ha="center", va="center",
            fontsize=13, fontweight="bold")

    # Scale bar (MDPI requires a scale on maps). 100 km, computed at its latitude.
    sb_lat, sb_lon0, km = 34.0, 124.85, 100.0
    sb_lon1 = sb_lon0 + km / (111.320 * np.cos(np.radians(sb_lat)))
    ax.plot([sb_lon0, sb_lon1], [sb_lat, sb_lat], color="black", linewidth=2.6,
            transform=proj, solid_capstyle="butt", zorder=6)
    for x in (sb_lon0, sb_lon1):
        ax.plot([x, x], [sb_lat - 0.07, sb_lat + 0.07], color="black",
                linewidth=2.6, transform=proj, zorder=6)
    ax.text(0.5 * (sb_lon0 + sb_lon1), sb_lat + 0.14, "100 km", ha="center",
            va="bottom", fontsize=9, fontweight="bold", transform=proj, zorder=6)

    # Inset: regional context
    inset = fig.add_axes([0.08, 0.55, 0.18, 0.30],
                          projection=ccrs.PlateCarree())
    inset.set_extent([110, 140, 25, 50], crs=ccrs.PlateCarree())
    inset.add_feature(cfeature.OCEAN, facecolor="#e6f1fb")
    inset.add_feature(cfeature.LAND, facecolor="#f5efe2",
                      edgecolor="#7c7c7c", linewidth=0.4)
    inset.add_feature(cfeature.COASTLINE, linewidth=0.4)
    inset.add_patch(plt.Rectangle((124.4, 33.5), 6, 5.7,
                                   facecolor="none", edgecolor="red",
                                   linewidth=1.4, transform=ccrs.PlateCarree()))
    inset.set_title("E Asia", fontsize=8, pad=2)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=600, bbox_inches="tight")  # MDPI: >=600 dpi
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
