# Tidal Aliasing Bias Analysis for Korean Intertidal Mapping

A research project quantifying satellite tidal aliasing bias for intertidal mapping along the macrotidal Korean coast.

## Research Question

How well do sun-synchronous optical satellites (Landsat, Sentinel-2) sample the full tidal range over Korean tidal flats? What is the magnitude and spatial-temporal pattern of tidal aliasing bias, and what are its implications for waterline-method DEM generation?

## Study Sites

Five major tidal-flat regions along the Korean coast:

| Site | Region | Approx. Lat/Lon | Tidal Range | Note |
|---|---|---|---|---|
| Ganghwa-do | NW (Gyeonggi Bay) | 37.60°N, 126.45°E | ~8 m | Largest tidal range in Korea |
| Garorim Bay | West (Chungnam) | 37.00°N, 126.40°E | ~6 m | Natural, Ramsar candidate |
| Gomso Bay | West (Jeonbuk) | 35.60°N, 126.60°E | ~6 m | Ryu et al. (2002) site |
| Hampyeong Bay | SW (Jeonnam) | 35.10°N, 126.40°E | ~4 m | Transition zone |
| Suncheon Bay | South (Jeonnam) | 34.90°N, 127.50°E | ~3 m | Ramsar wetland |

## Data Sources

| Source | Use | Access |
|---|---|---|
| Landsat 5/7/8/9 (GEE) | Image acquisition metadata (timestamps) | Google Earth Engine |
| Sentinel-2 A/B (GEE) | Image acquisition metadata (timestamps) | Google Earth Engine |
| FES2014 global tide model | Tide height at image acquisition times | AVISO (registration required) |
| KHOA tide gauges | Validation of FES2014 predictions | Korea Hydrographic & Oceanographic Agency |

## Methodology

1. **GEE metadata extraction**: Pull acquisition timestamps for all Landsat and Sentinel-2 scenes covering each site (1984-2025).
2. **Tide computation**: Use pyTMD with FES2014 to compute tide height at each acquisition time.
3. **KHOA cross-validation**: Compare FES2014 predictions to nearest tide-gauge observations.
4. **Aliasing statistics**:
   - **Spread**: observed tide range / astronomical tide range
   - **Offset (low/high)**: proportion of extreme tides never observed
   - **Distribution uniformity**: KS test against uniform sampling
5. **Comparative analysis**: by sensor, by site, by sub-period.

## Project Structure

```
tidalflat/
├── config/              # Site definitions, settings
├── data/
│   ├── raw/             # GEE metadata exports, FES2014 NetCDF, KHOA CSV
│   ├── processed/       # Tide-calculated tables
│   └── outputs/         # Figures, tables for paper
├── notebooks/           # Analysis notebooks
├── src/
│   ├── gee/             # GEE metadata extraction
│   ├── tides/           # FES2014, KHOA modules
│   ├── analysis/        # Aliasing statistics
│   └── visualization/   # Plotting
└── scripts/             # Runnable entry points
```

## Setup

```bash
# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Authenticate Earth Engine
earthengine authenticate

# Download FES2014 (requires AVISO account; place under data/raw/fes2014/)
# See: https://www.aviso.altimetry.fr/en/data/products/auxiliary-products/global-tide-fes.html
```

## Roadmap

- [x] Project skeleton
- [ ] Site definitions and KHOA station mapping
- [ ] GEE metadata extraction (Landsat 5/7/8/9, Sentinel-2)
- [ ] FES2014 tide computation
- [ ] KHOA tide observation ingestion
- [ ] Tidal aliasing statistics
- [ ] Visualization and paper-ready outputs

## References

- Bishop-Taylor, R. et al. (2019). Between the tides: modelling the elevation of Australia's exposed intertidal zone at continental scale. *ECSS* 223, 115-128.
- Sagar, S. et al. (2017). Extracting the intertidal extent and topography of the Australian coastline from a 28 year time series of Landsat observations. *RSE* 195, 153-169.
- Ryu, J.-H. et al. (2002). Waterline extraction from Landsat TM data in a tidal flat: A case study in Gomso Bay, Korea. *RSE* 83(3), 442-456.
- Geoscience Australia, `eo-tides` package — https://geoscienceaustralia.github.io/eo-tides/
