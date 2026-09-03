"""iTunes Search API：曲庫查不到時的兩件事——別名與試聽片段。

**為什麼需要這一層。** ReccoBeats 曲庫查不到的歌，過去只能回 None，
那些曲目的特徵全空，品味向量畫出來是一整排 0.00。實際查下去發現有兩個原因，
iTunes 剛好兩個都解得掉（NOTES #38、#39）：

1. **曲庫其實有這首歌，只是名字不同一套。** 曲庫是 Spotify 血統，
   茄子蛋在裡面叫 EggPlantEgg、草東沒有派對叫 No Party For Cao Dong。
   iTunes 同一首歌在 TW 與 US 商店各有一組寫法，用 `/lookup` 拿同一個 trackId
   在另一個商店的中繼資料，就等於一組免費的中英對照表。
2. **曲庫真的沒有這首歌。** 那就要音檔——iTunes 每首歌附一段 30 秒試聽，
   免金鑰，長度與大小天生落在分析端點的 30 秒／5MB 限制內。

實測（2026-09-03）：
  * 分析端點文件只列 MP3/OGG/WAV/AIFF，但實際吃 iTunes 的 m4a（AAC）沒問題。
  * 華語曲名要搜 TW 商店。美國商店的「大風吹」查不到草東，只會回 MC HotDog。
  * 同一首歌在 US 商店可能連曲名都換掉（大風吹→Simon Says、浪子回頭→Back Here
    Again），所以別名要連曲名一起收。
"""
from __future__ import annotations

import logging
from typing import Dict, List, NamedTuple, Optional

from app.config import get_settings
from app.core.normalize import bilingual_parts, same_artist, same_title
from app.services.http import get_bytes, get_json

log = logging.getLogger("museek.itunes")

# 分析端點的上限就是 5MB。試聽片段實測約 1MB，超過的一定不是我們要的東西。
PREVIEW_MAX_BYTES = 5 * 1024 * 1024
SEARCH_LIMIT = 5
# 一首歌最多送幾種搜尋字串。每多一種就多一趟請求 × 商店數，
# 補救本來就有時間預算，寬鬆到沒有上限反而會讓 /api/session 卡住。
MAX_SEARCH_TERMS = 3


class TrackMatch(NamedTuple):
    """iTunes 上找到的同一首歌。

    artist_names／titles 是各商店的寫法（保序去重），拿去回頭查 ReccoBeats 曲庫；
    preview_url 是 30 秒試聽片段，前者查不到時才用得上。
    """

    track_id: Optional[int]
    store: str
    artist_names: List[str]
    titles: List[str]
    preview_url: Optional[str]


def _dedupe(values: List[str]) -> List[str]:
    out, seen = [], set()
    for value in values:
        text = (value or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _accepts(artist: str, title: str, result: Dict) -> bool:
    """只收「同一首歌」。曲名對不上就寧可沒有特徵——錯配會污染整支品味向量。"""
    if not same_title(title, result.get("trackName") or ""):
        return False
    if not artist.strip():
        return True      # 切不出歌手時（頻道名也空）只能靠曲名
    return same_artist(artist, result.get("artistName") or "")


def _search_terms(artist: str, title: str) -> List[str]:
    """搜尋字串候選，由精確到寬鬆（去重、保序）。

    中英並列的寫法整串送出去常常回 0 筆：「陳綺貞 Cheer Chen 魚 Fish」查無，
    「陳綺貞 魚」才查得到（NOTES #41）。所以並列的兩半要各配一次——
    非拉丁那組配 TW 商店、拉丁那組配 US 商店，剛好是兩邊各自的寫法。
    """
    artist_latin, artist_cjk = bilingual_parts(artist)
    title_latin, title_cjk = bilingual_parts(title)
    pairs = [
        (artist.strip(), title.strip()),
        (artist_cjk or artist.strip(), title_cjk),
        (artist_latin or artist.strip(), title_latin),
    ]
    terms: List[str] = []
    for name, song in pairs:
        if not song.strip():
            continue
        term = " ".join(part for part in (name.strip(), song.strip()) if part)
        if term and term not in terms:
            terms.append(term)
    return terms[:MAX_SEARCH_TERMS]


async def _search(term: str, store: str) -> List[Dict]:
    settings = get_settings()
    try:
        data = await get_json(
            f"{settings.itunes_base_url}/search",
            params={"term": term, "entity": "song", "limit": SEARCH_LIMIT, "country": store},
        )
    except Exception as error:  # noqa: BLE001
        log.warning("iTunes 搜尋失敗（%s）：%s", store, error)
        return []
    return data.get("results") or []


async def _lookup(track_id: int, store: str) -> Optional[Dict]:
    """同一個 trackId 在另一個商店的中繼資料——中英對照就是這樣拿的。"""
    settings = get_settings()
    try:
        data = await get_json(f"{settings.itunes_base_url}/lookup",
                              params={"id": track_id, "country": store})
    except Exception as error:  # noqa: BLE001
        log.warning("iTunes lookup 失敗（%s）：%s", store, error)
        return None
    results = data.get("results") or []
    return results[0] if results else None


async def lookup_track(artist: str, title: str) -> Optional[TrackMatch]:
    """在 iTunes 上找出同一首歌，連同各商店的寫法一起回傳。找不到回 None。"""
    settings = get_settings()
    stores = settings.itunes_stores
    terms = _search_terms(artist, title)
    if not terms:
        return None

    for term in terms:
        for store in stores:
            for result in await _search(term, store):
                if not _accepts(artist, title, result):
                    continue

                names = [result.get("artistName") or ""]
                titles = [result.get("trackName") or ""]
                track_id = result.get("trackId")
                for other in stores:
                    if other == store or not track_id:
                        continue
                    alias = await _lookup(track_id, other)
                    if alias:
                        names.append(alias.get("artistName") or "")
                        titles.append(alias.get("trackName") or "")

                log.info("iTunes 找到：%s - %s（%s 商店，搜尋字串「%s」）",
                         result.get("artistName"), result.get("trackName"), store, term)
                return TrackMatch(track_id=track_id, store=store,
                                  artist_names=_dedupe(names), titles=_dedupe(titles),
                                  preview_url=result.get("previewUrl"))
    return None


async def fetch_preview(url: str) -> Optional[bytes]:
    """下載試聽片段。失敗回 None——這是加分路徑，不該讓整個 session 掛掉。"""
    try:
        return await get_bytes(url, max_bytes=PREVIEW_MAX_BYTES,
                               timeout=get_settings().analysis_timeout)
    except Exception as error:  # noqa: BLE001
        log.warning("試聽片段下載失敗：%s", error)
        return None
