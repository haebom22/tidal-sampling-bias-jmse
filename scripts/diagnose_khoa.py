"""Probe each KHOA Open API endpoint to verify the URL/key combination.

Usage:

    export KHOA_API_KEY="your-data-go-kr-key"
    python -m scripts.diagnose_khoa

The script issues one minimal request to each configured API and prints
the HTTP status, parsed row count, and a sample row. If any endpoint
returns 0 rows, edit ``config/khoa_apis.yaml`` to match the URL shown in
your data.go.kr dashboard.
"""

from __future__ import annotations

import logging
from datetime import date

from src.tides.khoa import diagnose

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# 가이드 PDF의 샘플 날짜를 사용 — 데이터가 확실히 publish된 시점.
#   tide_hourly      : reqDate=YYYYMMDD (가이드 샘플: 20240809 군산)
#   tide_deviation   : reqDate=YYYYMM   (가이드 샘플: 202410 군산)
#   tide_extreme     : reqDate 없음     (전체 이력 반환)
#   msl              : reqDate 없음     (전체 이력 반환)
APIS = [
    ("tide_hourly",     "DT_0018", date(2024, 8, 9)),     # 군산
    ("tide_deviation",  "DT_0018", date(2024, 10, 1)),    # 군산
    ("tide_extreme",    "DT_0018", None),                  # reqDate 없음
    ("msl",             "DT_0001", None),                  # reqDate 없음
]


def main() -> None:
    print(f"{'API':18s} {'HTTP':>4s} {'code':>5s} {'page1':>7s} {'total':>7s}  url")
    print("-" * 130)
    for api_id, station, day in APIS:
        try:
            info = diagnose(api_id=api_id, station_code=station, day=day)
            code = info.get("result_code") or "-"
            total = info.get("total_count")
            total_str = str(total) if total is not None else "?"
            print(
                f"{api_id:18s} {info['status_code']:>4d} {code:>5s} {info['rows_parsed']:>7d} {total_str:>7s}  {info['request_url']}"
            )
            if info.get("result_msg"):
                print(f"  msg   : {info['result_msg']}")
            if info["sample_row"]:
                print(f"  sample: {info['sample_row']}")
            else:
                print(f"  raw   : {info['raw_head'][:300]}")
        except Exception as exc:  # noqa: BLE001
            print(f"{api_id:18s} ERR  -     -      -      {exc}")
        print()


if __name__ == "__main__":
    main()
