"""把備援種子池解析成 data/vibe_seeds.json。

用法：  RECCOBEATS_MODE=live .venv/bin/python scripts/verify_vibe_seeds.py [--per-artist 3]

對 seed_pool.POOL 裡的每一位，向曲庫要曲目與音訊特徵，
只留下**真的解得出 recco_id 且真的有特徵**的那幾首。查不到的會列出來，
那份名單就是「清單該換人了」的訊號——曲庫的收錄範圍會變，這支腳本要定期重跑。

每一列都記下 `region`（asia／west）。亞洲候選的名額是照這個欄位算的，
沒有它 pipeline 只能看歌手名硬猜，而曲庫的寫法跟清單不見得一樣
（sodagreen 全小寫、Leo王 大小寫不同），猜出來的東西不能拿來當保證。

ReccoBeats 有速率限制（NOTES #38），連續打會開始回 429，
所以每一趟之間留一點間隔——這支腳本不趕時間，被擋下來重跑才是浪費。

不燒任何 YouTube 配額（完全不碰 YouTube），只打 ReccoBeats。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings              # noqa: E402
from app.services import reccobeats, seed_pool   # noqa: E402

PER_ARTIST_DEFAULT = 3      # 每位歌手留幾首。留多一點，特徵空間的覆蓋才夠密
CANDIDATES_PER_ARTIST = 20  # 從曲目清單的前幾首裡挑（一次批次查特徵就夠）
PACE_SECONDS = 1.0          # 每位歌手之間的間隔，避開 429


async def resolve(name: str, per_artist: int) -> list:
    tracks = [t for t in await reccobeats.artist_catalog([name]) if t.get("recco_id")]
    if not tracks:
        return []
    tracks = tracks[:CANDIDATES_PER_ARTIST]
    features = await reccobeats.get_audio_features([t["recco_id"] for t in tracks])

    rows = []
    for track in tracks:
        found = features.get(track["recco_id"])
        if not found:
            continue
        rows.append({
            "recco_id": track["recco_id"],
            # 歌手名記曲庫的寫法，不是我們清單裡的寫法——日後比對才對得上
            "artist": track.get("artist") or name,
            "title": track.get("title", ""),
            # region 記我們清單裡的分區，不從曲庫回推：曲庫沒有這個欄位，
            # 而「這位是不是亞洲歌手」是我們自己的主張，要留在自己的清單裡
            "region": seed_pool.region_of(name),
            "features": found,
        })
        if len(rows) >= per_artist:
            break
    return rows


async def main() -> int:
    per_artist = PER_ARTIST_DEFAULT
    if "--per-artist" in sys.argv:
        per_artist = int(sys.argv[sys.argv.index("--per-artist") + 1])

    if get_settings().reccobeats_mode == "stub":
        print("RECCOBEATS_MODE=stub——stub 曲庫解不出真的 id，這支腳本要對真實 API 跑。")
        return 1

    names = seed_pool.artists()
    print(f"解析 {len(names)} 位歌手，每位最多留 {per_artist} 首\n")

    seeds, missing = [], []
    for index, name in enumerate(names, 1):
        if index > 1:
            await asyncio.sleep(PACE_SECONDS)
        rows = await resolve(name, per_artist)
        region = seed_pool.region_of(name) or "?"
        if rows:
            seeds.extend(rows)
            print(f"  [{index:2}/{len(names)}] ✓ {name}（{region}）  {len(rows)} 首", flush=True)
        else:
            missing.append(name)
            print(f"  [{index:2}/{len(names)}] ✗ {name}（{region}）  曲庫查不到或沒有特徵", flush=True)

    os.makedirs(os.path.dirname(seed_pool.SEED_FILE), exist_ok=True)
    with open(seed_pool.SEED_FILE, "w", encoding="utf-8") as handle:
        json.dump({"seeds": seeds, "missing": missing}, handle, ensure_ascii=False, indent=2)

    by_region = {region: sum(1 for row in seeds if row["region"] == region)
                 for region in (seed_pool.ASIA, seed_pool.WEST)}
    print(f"\n寫入 {seed_pool.SEED_FILE}：{len(seeds)} 首，來自 {len(names) - len(missing)} 位歌手"
          f"（亞洲 {by_region[seed_pool.ASIA]} 首、歐美 {by_region[seed_pool.WEST]} 首）")
    if missing:
        print(f"查不到的 {len(missing)} 位：{'、'.join(missing)}")
        print("這幾位請在 seed_pool.POOL 換掉——留著只是每次都白跑一趟。")

    # 池子太小的話備援等於沒有備援，這裡要當成失敗。
    # 亞洲那一區另外算一次：候選注入完全靠它，它空了「多一點亞洲」就是空話，
    # 而總數還是會漂亮地過關——只看總數的檢查看不出這種故障。
    ok = len(seeds) >= 20 and by_region[seed_pool.ASIA] >= 15
    if len(seeds) < 20:
        print("\n⚠️ 解出來的曲目太少（< 20），備援種子池不足以涵蓋特徵空間。")
    if by_region[seed_pool.ASIA] < 15:
        print("\n⚠️ 亞洲曲目太少（< 15），候選注入補不出該有的比重。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
