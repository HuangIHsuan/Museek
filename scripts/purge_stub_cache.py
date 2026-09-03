"""清掉 feature_cache 裡的 stub 假資料。

從 stub 模式切到真實 ReccoBeats 時要跑一次。程式本身已經會拒用 stub 項目
（見 pipeline._features_for），這支腳本只是把佔空間的舊資料實際刪掉。

用法：  .venv/bin/python scripts/purge_stub_cache.py [--dry-run]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.repository import MemoryRepository  # noqa: E402


def is_stub(row: dict) -> bool:
    source = row.get("source")
    if source:
        return source == "stub"
    return str(row.get("recco_id", "")).startswith("stub-")


def main() -> int:
    dry = "--dry-run" in sys.argv
    path = MemoryRepository.CACHE_FILE
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        print(f"找不到 {path}，沒有東西要清。")
        return 0

    features = data.get("feature_cache") or {}
    stub_keys = [k for k, v in features.items() if is_stub(v)]
    print(f"feature_cache 共 {len(features)} 筆，其中 stub 假資料 {len(stub_keys)} 筆")

    if dry:
        for k in stub_keys[:5]:
            print(f"  會刪除：{k}")
        if len(stub_keys) > 5:
            print(f"  ...還有 {len(stub_keys) - 5} 筆")
        print("（--dry-run，沒有實際刪除）")
        return 0

    for k in stub_keys:
        features.pop(k, None)
    data["feature_cache"] = features
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, default=str)
    print(f"已刪除 {len(stub_keys)} 筆，剩下 {len(features)} 筆。")
    print("注意：video_cache 不受影響——那是真的 YouTube 查詢結果，刪掉要重花配額。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
