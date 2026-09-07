"""iTunes Search API：別名、試聽片段，以及曲風標籤。

**為什麼需要這一層。** ReccoBeats 曲庫查不到的歌，過去只能回 None，
那些曲目的特徵全空，品味向量畫出來是一整排 0.00。實際查下去發現有兩個原因，
iTunes 剛好兩個都解得掉（NOTES #38、#39）：

1. **曲庫其實有這首歌，只是名字不同一套。** 曲庫是 Spotify 血統，
   茄子蛋在裡面叫 EggPlantEgg、草東沒有派對叫 No Party For Cao Dong。
   iTunes 同一首歌在 TW 與 US 商店各有一組寫法，用 `/lookup` 拿同一個 trackId
   在另一個商店的中繼資料，就等於一組免費的中英對照表。
2. **曲庫真的沒有這首歌。** 那就要音檔——iTunes 每首歌附一段 30 秒試聽，
   免金鑰，長度與大小天生落在分析端點的 30 秒／5MB 限制內。
3. **曲風標籤**（`primaryGenreName`）。這是後來才加的第三件事，理由見下面那一節。

實測（2026-09-03）：
  * 分析端點文件只列 MP3/OGG/WAV/AIFF，但實際吃 iTunes 的 m4a（AAC）沒問題。
  * 華語曲名要搜 TW 商店。美國商店的「大風吹」查不到草東，只會回 MC HotDog。
  * 同一首歌在 US 商店可能連曲名都換掉（大風吹→Simon Says、浪子回頭→Back Here
    Again），所以別名要連曲名一起收。

## 為什麼曲風也走這裡（2026-09-07）

六個音訊維度分不出 citypop 與 soft rock，所以曲風是獨立的一軸（NOTES #49）；
但候選池裡沒有這個欄位，得從外面補。實測過三個來源，只有這個活著：

  * **Spotify**：原本選它，因為 ReccoBeats 的 payload 直接附了 Spotify 歌手 id。
    實測結果是**它已經不回 `genres` 了**——artist 物件只剩
    `external_urls / href / id / images / name / type / uri`，批次端點
    `/v1/artists?ids=` 直接 403。這條路是死的。
  * **MusicBrainz**：標籤夠細，但模糊比對會**很有信心地配錯人**
    （`Fujii Kaze` 配到 `Kaze` 並回 southern hip hop、`Sunset Rollercoaster`
    配到 `Rollercoaster`），一半請求回 503，而且限速 1 req/s。
  * **iTunes**：粒度較粗，但**它是唯一真的拿得到資料的**。實測 46 位歌手
    回了 40 種曲風字串，而且 TW 商店回中文、US 商店回英文，是同一套概念的
    兩種寫法（`華語流行樂`＝`Mandopop`、`嘻哈/饒舌`＝`Hip-Hop/Rap`）。

**要知道它的極限：iTunes 表達不出 citypop。** 山下達郎回 `J-Pop`、
落日飛車回 `成人當代`。R&B、嘻哈、獨立搖滾、J-Pop、K-Pop、華語流行都分得出來，
但那個最細的圈子分不出來——這是選它時就知道要付的代價，不是故障。

曲風掛在**歌手**身上（同一位歌手的每首歌共用一組標籤），因為那是這裡唯一
負擔得起的粒度：一位歌手一趟請求、行程內快取，之後整輪都是零請求。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set

from app.config import get_settings
from app.core import genres
from app.core.normalize import bilingual_parts, name_key, same_artist, same_title
from app.services.http import get_bytes, get_json, pacer

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


# iTunes 用 **403** 表達限流，不是 429——所以 http.get_json 的重試與退避
# （只認 429／5xx）對它完全不作用。實測打太快之後，連 0.5 秒間隔都會
# 10 次錯 8 次，而且冷卻 90 秒還沒退場。收到 403 就要讓整個服務退避，
# 不能只是記一行 log 繼續打下一位歌手。
RATE_LIMIT_BACKOFF = 60.0


async def _search(term: str, store: str) -> List[Dict]:
    settings = get_settings()
    try:
        data = await get_json(
            f"{settings.itunes_base_url}/search",
            params={"term": term, "entity": "song", "limit": SEARCH_LIMIT, "country": store},
        )
    except Exception as error:  # noqa: BLE001
        status = getattr(getattr(error, "response", None), "status_code", None)
        if status == 403:
            log.warning("iTunes 回 403（限流），暫停 %.0f 秒不再送出", RATE_LIMIT_BACKOFF)
            await _pace().back_off(RATE_LIMIT_BACKOFF)
        else:
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


# --- 曲風標籤 ---------------------------------------------------------------

# **iTunes 撐不起批量查詢，這個數字是量出來的不是猜的。** 實測 0.05 秒間隔
# ×4 併發打了近百次之後，它開始整片回 403；冷卻 90 秒、改成 0.5 秒間隔，
# 10 次仍然錯 8 次。官方文件給的量級是每分鐘約 20 次，所以這裡就照那個走：
# 3 秒一次、不併發。曲風是加分路徑，寧可慢、寧可這一輪少幾首有曲風，
# 也不能為了它把整個 iTunes 整合（別名、試聽片段）一起打進限流。
def _pace():
    """iTunes 專用的節流器。間隔從設定讀（http.reset_pacers 之後才會換新值）。"""
    return pacer("itunes", get_settings().itunes_pace_seconds, 1)

GENRE_SEARCH_LIMIT = 5      # 一位歌手看前幾筆結果就夠判斷曲風
GENRE_CACHE_MAX = 512       # 歌手數上限，滿了整份清掉（曲風不常變，重查很便宜）

# 歌手名 → 標準 slug 集合。**空集合是有意義的結果**（查過、認不出曲風），
# 所以用「鍵在不在」判斷有沒有查過，不能用值真假判斷——不然沒有曲風的歌手
# 每一輪都會被重問一次。
_genre_cache: Dict[str, Set[str]] = {}
_last_genre_ok: Optional[bool] = None


def reset_genre_cache() -> None:
    """清掉曲風快取（測試與長跑行程用）。"""
    global _last_genre_ok
    _genre_cache.clear()
    _last_genre_ok = None


def genre_status() -> str:
    """給 /api/health 用。unknown = 這個行程還沒查過任何一位歌手。"""
    if _last_genre_ok is None:
        return "unknown"
    return "ok" if _last_genre_ok else "degraded"


async def _genres_for_artist(name: str) -> Set[str]:
    """查一位歌手的曲風。查不到、或認不出來，都回空集合。

    **只收歌手名對得上的那幾筆。** iTunes 的搜尋是模糊的：搜「Anri」會混進
    另一位同名歌手的龐克曲目，搜「Sunset Rollercoaster」會回到 Korean Rock。
    不驗證的話，標到的曲風會是別人的——那比沒有曲風更糟，因為它會被當成事實
    拿去排序、還會佔掉曲風名額。

    商店依序試（TW 在前），**第一個給得出曲風的就停**：TW 商店同時收國際發行，
    多數歌手一趟就夠，不必每位都打兩趟。
    """
    global _last_genre_ok
    if not name.strip():
        return set()

    raw: List[str] = []
    for store in get_settings().itunes_stores:
        try:
            async with _pace():
                results = await _search(name, store)
            _last_genre_ok = True
        except Exception as error:  # noqa: BLE001
            log.warning("iTunes 曲風查詢失敗（%s）：%s", store, error)
            _last_genre_ok = False
            continue
        for result in results:
            if not same_artist(name, result.get("artistName") or ""):
                continue
            found = result.get("primaryGenreName")
            if found:
                raw.append(str(found))
        if raw:
            break                # 這個商店給得出來就不用再問下一個
    return genres.normalize(raw)


async def artist_genres(names: Sequence[str], limit: int = 0) -> Dict[str, Set[str]]:
    """{歌手名 name_key: 標準 slug 集合}。行程內快取，同一位只查一次。

    limit 是**這一輪最多對外查幾位**（0 = 不限）。查過的不算在內。
    沒有這個上限的話，一輪 50 首全是新歌手時就是 50 趟請求掛在推薦流程上；
    寧可這一輪少幾首有曲風，也不能讓使用者盯著轉圈——查不到曲風的候選
    在排序時本來就不受罰（見 ranker.score_candidate）。

    **同時發出，不要一位一位等。** 曲風是掛在推薦流程上的額外請求，循序跑的話
    25 位歌手就是 25 個往返疊加起來；送出節奏交給節流器控制，把網路延遲重疊掉。
    """
    seen_keys, wanted = set(), []
    for name in names:
        key = name_key(name or "")
        if key and key not in seen_keys:
            seen_keys.add(key)
            wanted.append(name.strip())

    missing = [n for n in wanted if name_key(n) not in _genre_cache]
    todo = missing[:limit] if limit > 0 else missing
    if todo:
        if len(_genre_cache) + len(todo) > GENRE_CACHE_MAX:
            _genre_cache.clear()
        found = await asyncio.gather(*(_genres_for_artist(name) for name in todo))
        for name, slugs in zip(todo, found):
            _genre_cache[name_key(name)] = slugs

    return {name_key(n): _genre_cache[name_key(n)]
            for n in wanted if name_key(n) in _genre_cache}


async def tag_candidates(candidates: Iterable[Dict], limit: int = 0) -> int:
    """就地把候選標上 `genres`，回傳實際標到的首數。

    曲風查的是**歌手**，所以同一位歌手的多首歌只花一趟請求——一份歌單或一池
    候選裡重複的歌手很多，這是這個粒度唯一划算的地方。
    """
    rows = [row for row in candidates if isinstance(row, dict)]
    names = [row.get("artist") or "" for row in rows]
    if not any(name.strip() for name in names):
        return 0

    found = await artist_genres(names, limit=limit)
    tagged = 0
    for row in rows:
        slugs = found.get(name_key(row.get("artist") or ""), set())
        if slugs:
            row["genres"] = sorted(slugs)
            tagged += 1
    return tagged
