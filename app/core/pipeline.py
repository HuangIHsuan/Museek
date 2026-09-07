"""把各模組串成 /api/session 與 /api/recommend 的實際流程。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from app.config import get_settings
from app.core import genres, profiler, ranker, regions
from app.core.normalize import cache_key, name_key, parse_source, split_artist_title
from app.core.quota import QuotaTracker
from app.core.resolver import VideoResolver
from app.db.repository import profile_expiry
from app.models import Constraints, Score, TrackResult
from app.services import itunes, llm, reccobeats, seed_pool, stub_data, youtube

log = logging.getLogger("museek.pipeline")


class SessionNotFound(Exception):
    pass


# --- 特徵取得（feature_cache 優先，非 YouTube 來源可長期保留）------------------

class RecoveryBudget:
    """一次請求最多補救幾首曲庫沒查到的歌。

    別名回查約 1 秒，再加上音訊分析約 3 秒。50 首都沒中的歌單若不設上限，
    /api/session 會卡上好幾分鐘——寧可少幾首有特徵，也不能讓使用者盯著轉圈。
    """

    def __init__(self, limit: int) -> None:
        self.left = max(0, limit)
        self.used = 0

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        self.used += 1
        return True


def _unique(values: List[str]) -> List[str]:
    """保序去重。別名常常跟原本的寫法一樣，重複送出去只是白白多一趟請求。"""
    out, seen = [], set()
    for value in values:
        key = name_key(value or "")
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


# 代打種子最多從歌手的前幾首挑，一次批次查特徵就夠（超過 40 個 id 要拆多趟）
PROXY_POOL = 40


async def _proxy_seed(artist_names: List[str], features: Dict[str, float],
                      note: str = "原曲不在曲庫") -> Optional[str]:
    """那首歌不在曲庫時的代打種子：同一位歌手、特徵最接近的那一首（NOTES #40）。

    推薦端點只吃曲目 id，但**種子不必是同一首歌**。曲庫沒收 HEADLOCK，
    Luci Gang 本人卻有 77 首——用分析出來的特徵挑最近的那首，
    候選池就落在對的鄰居裡，剩下的交給 Discovery Ranker 用真的品味向量排。
    """
    if not features:
        return None
    tracks = [t for t in await reccobeats.artist_catalog(artist_names) if t.get("recco_id")]
    if not tracks:
        return None
    tracks = tracks[:PROXY_POOL]

    found = await reccobeats.get_audio_features([t["recco_id"] for t in tracks])
    best, best_score = None, -1.0
    for track in tracks:
        candidate = found.get(track["recco_id"])
        if not candidate:
            continue
        score = ranker.similarity(features, candidate)
        if score > best_score:
            best, best_score = track, score
    if not best:
        return None
    log.info("種子曲：%s（相似度 %.3f，%s）", best["title"], best_score, note)
    return best["recco_id"]


async def _recover_via_itunes(artist: str, title: str, have_id: Optional[str],
                              budget: Optional[RecoveryBudget]
                              ) -> Tuple[Optional[str], Optional[str], Dict[str, float], str]:
    """曲庫第一趟沒查到時的補救，回傳 (recco_id, seed_id, features, source)。

    先用 iTunes 認出這首歌，那一趟同時給我們兩樣東西（NOTES #39）：

      1. **各商店的寫法**——曲庫是 Spotify 血統，茄子蛋在裡面叫 EggPlantEgg。
         帶著別名回頭查曲庫，多半查得到，而且拿到的是真的 recco_id，
         可以當推薦種子（分析出來的特徵沒有 id，當不了種子）。
      2. **30 秒試聽片段**——曲庫真的沒有這首歌時，丟進分析端點直接算特徵。

    順序不能反：有 recco_id 的那條路同時解決特徵與種子，分析只解決特徵。
    """
    settings = get_settings()
    if not settings.reccobeats_recovery:
        return have_id, None, {}, "reccobeats"
    if budget is not None and not budget.take():
        log.info("曲庫補救額度已用盡，略過 %s - %s", artist, title)
        return have_id, None, {}, "reccobeats"

    match = await itunes.lookup_track(artist, title)
    if not match:
        log.info("iTunes 找不到這首歌：%s - %s", artist, title)
        return have_id, None, {}, "reccobeats"

    # 1) 帶著別名回頭查曲庫
    titles = _unique([title, *match.titles])
    names = _unique([*match.artist_names, artist])
    recco_id = have_id
    if not recco_id:
        for alias_title in titles:
            recco_id = await reccobeats.search_track(artist, alias_title,
                                                     artist_aliases=match.artist_names)
            if recco_id:
                break
    if not recco_id:
        # 曲名搜尋有 3 字下限、又受翻譯影響；歌手曲目清單兩者都不受限
        recco_id = await reccobeats.search_track_via_artist(names, titles)
    if recco_id:
        features = (await reccobeats.get_audio_features([recco_id])).get(recco_id)
        if features:
            log.info("靠 iTunes 別名在曲庫找到：%s - %s（%s）",
                     artist, title, "／".join(match.artist_names))
            return recco_id, None, features, "reccobeats"

    # 2) 曲庫真的沒有（或有曲目卻沒有特徵）：分析試聽片段
    if not settings.reccobeats_analysis or not match.preview_url:
        return recco_id, None, {}, "reccobeats"
    audio = await itunes.fetch_preview(match.preview_url)
    if not audio:
        return recco_id, None, {}, "reccobeats"
    features = await reccobeats.extract_audio_features(audio)
    if not features:
        return recco_id, None, {}, "reccobeats"
    log.info("音訊分析補上特徵：%s - %s（iTunes %s 商店）", artist, title, match.store)

    # 3) 分析出來的曲目沒有 id，當不了種子——同一位歌手挑一首特徵最近的代打
    seed_id = None if recco_id else await _proxy_seed(names, features)
    return recco_id, seed_id, features, "analysis"


async def _features_for(repo, artist: str, title: str,
                        budget: Optional[RecoveryBudget] = None,
                        searched: Optional[Dict[str, Optional[str]]] = None) -> Optional[Dict]:
    """取得單曲特徵。feature_cache 優先，未命中才對外查。

    對外查有兩條路：先查 ReccoBeats 曲庫，查不到才用試聽片段做音訊分析。
    兩者的特徵是同一個尺度，可以混在同一支向量裡（NOTES #38）。

    快取項目會標記來源。從 stub 切到真實模式時，**舊的 stub 假特徵絕對不能再取用**——
    否則真實模式會端出一整份看起來正常、實際上是雜湊亂數的品味向量（NOTES #35）。
    """
    stub_mode = get_settings().reccobeats_mode == "stub"
    key = cache_key(artist, title)
    cached = await repo.get_features([key])
    if key in cached and _is_fresh_miss(cached[key]):
        # 查過、確定查不到的：短時間內不要再查一次。整份歌單重新解析時，
        # 沒有這一層的話那些查不到的曲目會把整套失敗查詢（含 iTunes 補救）重跑一遍。
        return None
    if key in cached and cached[key].get("source") != "miss":
        row = cached[key]
        # 沒有 source 的是早期寫入的項目，一律當成 stub 看待
        source = row.get("source") or ("stub" if str(row.get("recco_id", "")).startswith("stub-") else "reccobeats")
        if stub_mode or source != "stub":
            return {"recco_id": row.get("recco_id"), "seed_id": row.get("seed_id"),
                    "features": row.get("features") or {},
                    "popularity": row.get("popularity"), "source": source}

    if stub_mode:
        payload = {
            "recco_id": stub_data.stub_recco_id(artist, title),
            "features": stub_data.stub_features(artist, title),
            "popularity": stub_data.stub_popularity(artist, title),
            "source": "stub",
        }
        await repo.set_features(key, payload)
        return payload

    # 這一輪預抓已經查過的就不要再查一次（含查不到的）
    if searched is not None and key in searched:
        recco_id = searched[key]
    else:
        recco_id = await reccobeats.search_track(artist, title)
    # 曲庫有這首歌但沒有特徵時也要走補救，recco_id 仍然留著當推薦種子
    features = (await reccobeats.get_audio_features([recco_id])).get(recco_id) if recco_id else None
    source, seed_id = "reccobeats", None
    if not features:
        recco_id, seed_id, features, source = await _recover_via_itunes(
            artist, title, recco_id, budget
        )
    if not features:
        if not (recco_id or seed_id):
            # 記成 miss，但只記一天——特徵之後可能補得上，長期記下來會擋住重試
            await repo.set_features(key, {"source": "miss", "features": {},
                                          "missed_at": datetime.now(tz=timezone.utc).isoformat()})
            return None
        # 特徵補不上、但曲庫裡認得這首歌：id 還是能當推薦種子。
        # 這裡回 None 的話連種子都會一起丟掉，單曲入口就完全沒得推薦了。
        # 不寫進快取——特徵下次可能補得上，記下來反而擋住重試。
        log.info("查不到音訊特徵，但保留推薦種子：%s - %s", artist, title)
        return {"recco_id": recco_id, "seed_id": seed_id, "features": {},
                "popularity": None, "source": source}
    payload = {"recco_id": recco_id, "seed_id": seed_id, "features": features,
               "popularity": None, "source": source}
    await repo.set_features(key, payload)
    return payload


async def _prefetch_features(repo, items: List[Dict], on_progress) -> Dict[str, Optional[str]]:
    """先把整份歌單的特徵批次查好、寫進快取，之後逐首處理時就幾乎不用再對外。

    原本每首歌要兩次 ReccoBeats 請求（search 一次、audio-features 一次），
    50 首就是 100 次循序請求、實測 75 秒。audio-features 有批次端點
    （一次 40 個 id），所以第二種請求可以從 50 次壓到 2 次。

    search 沒有批次端點，只能一首一首查——那部分靠節流器控制送出節奏，
    在不觸發 429 的前提下盡量快（ReccoBeats 的限制是針對瞬間併發，
    不是每秒總量，見 NOTES #39）。
    """
    if get_settings().reccobeats_mode == "stub":
        return {}

    pending = []          # [(cache_key, artist, title)]
    for item in items:
        artist, title = split_artist_title(item.get("raw_title", ""), item.get("channel"))
        if not title:
            continue
        pending.append((cache_key(artist, title), artist, title))

    cached = await repo.get_features([k for k, _, _ in pending])
    todo = [(k, a, t) for k, a, t in pending
            if k not in cached or not (_is_fresh_miss(cached[k]) or cached[k].get("features"))]
    total = len(todo)
    # cache_key -> recco_id，查過但找不到的記成 None。
    # 沒有這一份的話，後面逐首處理時會把同樣的 search 再打一次（實測請求數反而變多）。
    searched: Dict[str, Optional[str]] = {}
    if not todo:
        return searched

    # 第一階段：找出每首的 recco_id。同時發出多個請求把網路延遲重疊起來，
    # 送出節奏由節流器控制——ReccoBeats 擋的是「同時開始」，不是總量。
    found: Dict[str, tuple] = {}       # recco_id -> (cache_key, artist, title)
    done = 0

    async def resolve(key: str, artist: str, title: str) -> None:
        nonlocal done
        recco_id = await reccobeats.search_track(artist, title)
        searched[key] = recco_id
        if recco_id:
            found[recco_id] = (key, artist, title)
        done += 1
        await on_progress(done, total, title)

    await asyncio.gather(*(resolve(k, a, t) for k, a, t in todo))

    # 第二階段：一次把所有特徵批次要回來
    if not found:
        return searched
    features = await reccobeats.get_audio_features(list(found))
    for recco_id, feature in features.items():
        key, _artist, _title = found.get(recco_id, (None, None, None))
        if key and feature:
            await repo.set_features(key, {"recco_id": recco_id, "seed_id": None,
                                          "features": feature, "popularity": None,
                                          "source": "reccobeats"})
    return searched


MISS_TTL_SECONDS = 24 * 3600


def _is_fresh_miss(row: Dict) -> bool:
    """這筆是不是「還在有效期內的查無此曲」。"""
    if row.get("source") != "miss":
        return False
    raw = row.get("missed_at")
    if not raw:
        return True
    try:
        missed_at = datetime.fromisoformat(str(raw))
    except ValueError:
        return True
    if missed_at.tzinfo is None:
        missed_at = missed_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(tz=timezone.utc) - missed_at).total_seconds()
    return age < MISS_TTL_SECONDS


# --- /api/session ------------------------------------------------------------

async def _fetch_items(quota: QuotaTracker, kind: str, source_id: str) -> List[Dict]:
    """讀取歌單或單曲的曲目清單，兩者都走金鑰輪替：一把耗盡就換下一把。"""
    settings = get_settings()
    fetch = youtube.fetch_playlist_items if kind == "playlist" else youtube.fetch_video_items
    cost = (settings.quota_cost_playlist_items if kind == "playlist"
            else settings.quota_cost_videos)

    # stub 模式沒有金鑰，直接呼叫。
    if not youtube.is_live():
        return await fetch(source_id)

    items, used_key = None, None
    while items is None:
        used_key = await quota.active_key()
        if used_key is None:
            raise youtube.QuotaExceeded("所有 YouTube 金鑰的當日配額都已用盡")
        try:
            items = await fetch(source_id, api_key=used_key)
        except youtube.QuotaExceeded:
            await quota.mark_exhausted(used_key)
    await quota.spend(cost, key=used_key)
    return items


async def create_session(repo, quota: QuotaTracker, playlist_url: str) -> Dict:
    """建立工作階段並回傳結果。舊有的一次性 JSON 介面，行為不變。"""
    result = None
    async for event, payload in create_session_stream(repo, quota, playlist_url):
        if event == "session":
            result = payload
    assert result is not None
    return result


async def create_session_stream(repo, quota: QuotaTracker, playlist_url: str
                                ) -> AsyncGenerator[Tuple[str, Dict], None]:
    """同樣的流程，但逐步 yield 進度。

    逐首查音訊特徵是循序的外部請求，50 首實測要 70 秒以上。沒有進度回報的話
    使用者只看得到一顆停住的按鈕，會以為當掉了。
    """
    source = parse_source(playlist_url)
    kind, source_id = source.kind, source.id

    try:
        items = await _fetch_items(quota, kind, source_id)
    except youtube.PlaylistNotAccessible:
        # 「watch?v=...&list=...」的歌單可能是私人或已刪除，
        # 讀不到就退回那一首歌，不要讓使用者卡在錯誤畫面。
        if kind != "playlist" or not source.video_id:
            raise
        log.info("歌單 %s 讀不到，改以單曲 %s 建立品味", source_id, source.video_id)
        kind, source_id = "video", source.video_id
        items = await _fetch_items(quota, kind, source_id)

    budget = RecoveryBudget(get_settings().recovery_max_per_session)
    tracks: List[Dict] = []

    total = len(items)
    yield "progress", {"step": "fetched", "done": 0, "total": total,
                       "label": f"讀到 {total} 首曲目"}

    # 批次預抓特徵。進度由這一段回報——時間幾乎都花在這裡。
    updates: List[Dict] = []

    async def report(done: int, count: int, title: str) -> None:
        updates.append({"step": "analyze", "done": done, "total": count,
                        "label": f"分析曲目 {done}／{count}：{title[:24]}"})

    prefetch = asyncio.create_task(_prefetch_features(repo, items, report))
    while not prefetch.done():
        await asyncio.sleep(0.15)
        while updates:
            yield "progress", updates.pop(0)
    searched = await prefetch
    while updates:
        yield "progress", updates.pop(0)

    for item in items:
        artist, title = split_artist_title(item.get("raw_title", ""), item.get("channel"))
        if not title:
            continue
        enriched = await _features_for(repo, artist, title, budget, searched)
        tracks.append({
            "raw_title": item.get("raw_title", ""),
            "artist": artist,
            "title": title,
            "recco_id": (enriched or {}).get("recco_id"),
            "seed_id": (enriched or {}).get("seed_id"),
            "features": (enriched or {}).get("features") or {},
            "popularity": (enriched or {}).get("popularity"),
            "source": (enriched or {}).get("source"),
            # 有 id 沒特徵的那種只能當種子，不能算進品味向量
            "matched": bool((enriched or {}).get("features")),
        })

    yield "progress", {"step": "profile", "done": total, "total": total,
                       "label": "整理你的品味輪廓"}

    # 整份歌單的曲風查完再建輪廓，曲風分布才進得了品味輪廓。查的是**歌手**，
    # 所以一份 50 首的歌單通常只花十幾趟請求（同一位歌手只查一次）。
    await _tag_genres(tracks)

    (vector, popularity_mean, seen_artists, matched, unmatched, warning,
     genre_weights) = profiler.build_profile(tracks)
    if genre_weights:
        log.info("歌單曲風分布：%s", "、".join(
            f"{genres.label(slug)} {weight}" for slug, weight in genre_weights.items()))
    analyzed = sum(1 for t in tracks if t.get("source") == "analysis")
    if warning and kind == "video":
        # 單曲入口只有一首歌，「歌單有較多曲目未收錄」的說法會讓人一頭霧水。
        # 有沒有種子是兩種不同的處境：有種子還推得動，沒有就真的無從推薦。
        if any(t.get("recco_id") or t.get("seed_id") for t in tracks):
            warning = "這首歌查不到音訊特徵，推薦會以曲庫裡最接近的同名曲目為種子，並更依賴你描述的氛圍。"
        else:
            warning = ("這首歌在 ReccoBeats 曲庫與 iTunes 都查不到，沒有音訊特徵也沒有推薦種子。"
                       "換一首在串流平台上找得到的歌，或改貼整份歌單會更準。")
    session_id = uuid.uuid4().hex

    await repo.save_profile({
        "session_id": session_id,
        "playlist_id": source_id,
        "source_kind": kind,
        "tracks": tracks,
        "vector": vector,
        "popularity_mean": popularity_mean,
        # 品味輪廓的第二支：曲風分布。使用者沒明講曲風時，排序就照這份比。
        "genre_weights": genre_weights,
        "seen_artists": seen_artists,
        "blacklist": [],
        "down_votes": {},          # 歌手 → 連續 👎 次數
        "last_round": [],          # 上一輪回傳的候選，回饋重排時要用
        "last_prompt": "",
        "created_at": datetime.now(tz=timezone.utc),
        "expires_at": profile_expiry(),
    })

    yield "session", {
        "session_id": session_id,
        "profile": {"vector": vector, "popularity_mean": popularity_mean, "warning": warning,
                    "top_artists": _top_artists(tracks), "genres": genre_weights},
        "matched": matched,
        "unmatched": unmatched,
        # 其中幾首的特徵是靠試聽片段分析出來的，不是曲庫查到的——這件事要看得見
        "analyzed": analyzed,
    }


# --- 沒有歌單的入口：情境 → 氛圍 ---------------------------------------------

VIBE_SEED_ARTISTS = 5      # 最多向幾位歌手各要一顆種子（推薦端點也只吃 5 顆）
FALLBACK_RESOLVE_MAX = 8   # 沒有預先解析好的池子時，最多即時解析幾位（每位約兩趟請求）


async def _seeds_from_artists(artist_names: List[str], vector: Dict[str, float],
                              limit: int = VIBE_SEED_ARTISTS) -> List[str]:
    """每位歌手挑一首最貼近目標特徵的歌當種子。

    只挑一首是刻意的：同一位歌手連挑兩首會把候選池整個壓到他的鄰居身上，
    幾位歌手各一首，出來的東西才有情境該有的寬度。
    """
    seeds: List[str] = []
    for name in artist_names:
        if len(seeds) >= limit:
            break
        seed = await _proxy_seed([name], vector, note=f"{name} 最貼近這個氛圍的一首")
        if seed and seed not in seeds:
            seeds.append(seed)
    return seeds


async def _fallback_seeds(vector: Dict[str, float]) -> List[str]:
    """備援種子：從人工維護的池子裡挑特徵最貼近的幾首（見 services/seed_pool）。

    先讀 verify_vibe_seeds.py 預先解析好的檔案——零 API 呼叫，而且每一首都保證查得到。
    沒有那個檔就退回即時解析，慢一點但不必先跑腳本。
    """
    settings = get_settings()
    if settings.reccobeats_mode == "stub":
        return []      # stub 曲庫沒有真的 id，即時解析只會空跑一輪
    pool = seed_pool.load()
    if pool:
        picked = seed_pool.pick(pool, vector, ranker.similarity, limit=VIBE_SEED_ARTISTS,
                                asia_min=settings.seed_asia_min)
        log.info("備援種子（預解析池）：%s",
                 "、".join(f"{row['artist']} - {row['title']}" for row in picked))
        return [row["recco_id"] for row in picked]

    log.info("沒有 data/vibe_seeds.json，備援種子改為即時解析"
             "（跑 scripts/verify_vibe_seeds.py 可以省掉這一段）")
    return await _seeds_from_artists(seed_pool.artists()[:FALLBACK_RESOLVE_MAX], vector)


async def _vibe_seeds(artist_names: List[str], vector: Dict[str, float]) -> Tuple[List[str], str]:
    """回傳 (種子 id, 來源)。來源是 "vibe"／"fallback"／"none"。

    模型讀出來的歌手優先——那是照著使用者這一次的情境挑的，比我們寫死的池子貼近。
    一位都沒對上才退到備援；退了就要講出來，不能安靜地換掉推薦的起點。
    """
    if not artist_names:
        # 這條路以前什麼都沒記。「LLM 沒給歌手」與「給了但查不到」是兩種故障，
        # log 分不出來的話，線上只會看到一個沒有頭緒的 no_seeds（NOTES #4）。
        log.warning("氛圍推薦：LLM 沒有給任何起點歌手（多半是降級或回傳格式不對）")
    else:
        seeds = await _seeds_from_artists(artist_names[:VIBE_SEED_ARTISTS], vector)
        if seeds:
            return seeds, "vibe"
        log.warning("氛圍推薦：%s 都不在 ReccoBeats 曲庫裡，改用備援種子",
                    "、".join(artist_names[:VIBE_SEED_ARTISTS]))

    fallback = await _fallback_seeds(vector)
    return (fallback, "fallback") if fallback else ([], "none")


async def create_vibe_session(repo, prompt: str) -> Dict:
    """只憑一段情境建立工作階段：LLM 讀出氛圍，我們把它換算成向量與種子。

    與 create_session 的差別只有「品味從哪裡來」：那邊是把聽過的歌平均起來，
    這邊是從情境推出「典型的那一首」。之後的候選、排序、驗證、理由完全共用同一條路。

    兩次 LLM 呼叫互不相干（一次要限制、一次要氛圍），並行送出省掉一輪往返；
    使用者盯著轉圈的時間就是這兩次呼叫的長度。
    """
    intent, vibe = await asyncio.gather(llm.parse_intent(prompt), llm.analyze_vibe(prompt))
    constraints = Constraints(**(intent.get("constraints") or {}))
    vector = ranker.target_vector(vibe.get("target"), constraints)
    seed_artists = vibe.get("seed_artists") or []
    # 情境入口沒有歌單可統計，曲風分布就用氛圍讀出來的那幾種。
    # 全部給同樣的權重——模型給的是一個沒有次序的清單，硬分主次是我們加的。
    genre_weights = {slug: 1.0 for slug in (vibe.get("genres") or [])}
    seeds, seed_source = await _vibe_seeds(seed_artists, vector)

    session_id = uuid.uuid4().hex
    await repo.save_profile({
        "session_id": session_id,
        "playlist_id": "",
        "source_kind": "vibe",
        "tracks": [],              # 沒有聽過的歌，所以也沒有「已聽過」可以排除
        "vector": vector,
        "popularity_mean": 50.0,
        "genre_weights": genre_weights,
        "seen_artists": [],        # 同溫層懲罰要有聽歌紀錄才成立，這裡一律不罰
        "blacklist": [],
        "down_votes": {},
        "last_round": [],
        "last_prompt": "",
        "seed_ids": seeds,
        "seed_source": seed_source,
        "vibe": vibe.get("vibe", ""),
        # 情境已經解析過一次，推薦時照著這份用，不必再問 LLM 同一個問題
        "intent": intent,
        "intent_prompt": prompt,
        "created_at": datetime.now(tz=timezone.utc),
        "expires_at": profile_expiry(),
    })
    return {"session_id": session_id, "vibe": vibe.get("vibe", ""), "vector": vector,
            "seed_artists": seed_artists, "seeds": len(seeds), "seed_source": seed_source}


async def vibe_recommend_stream(repo, quota: QuotaTracker, prompt: str
                                ) -> AsyncGenerator[Tuple[str, Dict], None]:
    """/api/recommend 沒帶 session_id 時走這條：先讀氛圍建 session，再接回原本的推薦流程。"""
    yield "thinking", {"step": "parse", "label": "讀取你描述的情境"}
    session = await create_vibe_session(repo, prompt)
    # 前端要拿這個 id 才送得出 👍👎，所以在第一首歌之前就得先給它
    yield "session", {"session_id": session["session_id"], "vibe": session["vibe"],
                      "vector": session["vector"], "seed_artists": session["seed_artists"],
                      # 用了備援種子就要看得見——推薦的起點被換掉了，這不是實作細節
                      "seed_source": session["seed_source"]}
    async for event in recommend_stream(repo, quota, session["session_id"], prompt):
        yield event


# --- 亞洲候選：候選池裡自己補進來的那一份 -------------------------------------

ASIA_LIVE_ARTISTS = 3       # 沒有預解析檔時，最多即時翻幾位亞洲歌手的曲目
ASIA_LIVE_PER_ARTIST = 40   # 每位翻前幾首（一次批次查特徵就夠）


def _as_candidate(row: Dict) -> Dict:
    """種子池的一列轉成候選的形狀。region 是我們自己的主張，跟著一起帶。

    genres 是 verify_vibe_seeds.py 預先解析好的。舊版的檔案沒有這個欄位，
    那時補進來的亞洲候選就沒有曲風可比——**不會被扣分**（genre_fit 回 None
    就整項拿掉），但也湊不進曲風名額。重跑那支腳本就會補上；
    在那之前，這些候選仍然會在推薦流程裡被現場標（只是多花幾趟請求）。
    """
    # region 照實抄，**缺值就留空**。原本這裡缺值預設成 asia，那在只有亞洲注入時
    # 看不出問題；現在曲風注入會從兩區一起抽，預設成 asia 等於把歐美的歌算成亞洲、
    # 灌水亞洲佔比。空字串的意思是「沒有證據」，regions.region_of 本來就這樣定義。
    return {"recco_id": row.get("recco_id", ""), "artist": row.get("artist", ""),
            "title": row.get("title", ""), "features": row.get("features") or {},
            "genres": list(row.get("genres") or []),
            "popularity": None, "region": row.get("region") or ""}


async def _asia_from_catalog(vector: Dict[str, float], want: int, center: float,
                             constraints: Constraints,
                             wanted_genres: Optional[Dict[str, float]] = None) -> List[Dict]:
    """沒有預解析檔時的後路：現場翻幾位亞洲歌手的曲目清單。

    比讀檔慢（每位約兩趟請求），但不需要先跑腳本。挑哪幾位是隨機的——
    固定前幾位的話，所有人的亞洲候選會是同一批歌手。
    """
    names = seed_pool.artists(seed_pool.ASIA)
    picked = random.sample(names, min(ASIA_LIVE_ARTISTS, len(names)))
    rows: List[Dict] = []
    for name in picked:
        tracks = [t for t in await reccobeats.artist_catalog([name])
                  if t.get("recco_id")][:ASIA_LIVE_PER_ARTIST]
        if not tracks:
            continue
        found = await reccobeats.get_audio_features([t["recco_id"] for t in tracks])
        rows.extend({**track, "features": found[track["recco_id"]], "region": seed_pool.ASIA}
                    for track in tracks if found.get(track["recco_id"]))
    log.info("亞洲候選改為即時解析（%s），取得 %d 首", "、".join(picked), len(rows))
    # 即時解析這條路的曲目現場標曲風（歌手數不多，而且馬上會被快取住）
    await _tag_genres(rows)
    return _draw_from_pool(rows, vector, want, center, constraints, wanted_genres)


def _draw_from_pool(rows: List[Dict], vector: Dict[str, float], want: int, center: float,
                    constraints: Constraints,
                    wanted_genres: Optional[Dict[str, float]] = None) -> List[Dict]:
    """從已經篩好的種子池列裡抽 want 首，**優先抽符合情境上下限、而且曲風對得上的**。

    地區名額只在同一層裡對調（ranker.region_quota 紀律 1），所以補進來的歌
    如果違反「不要太吵」，它就永遠待在後段那一層，名額再怎麼保也拉不上來——
    補了 12 首、前五名只有 1 首亞洲，就是這樣來的。

    合格的湊不滿才拿不合格的補。那幾首排不到前面，但候選多一點總比少一點好，
    而且下一輪使用者按了 👍👎、向量移動之後，它們可能就合格了。
    """
    fits = [row for row in rows
            if ranker.passes_hard_filter(constraints, row.get("features") or {})]
    # 使用者點名曲風時，這一份補給也要照那個曲風補。不然兩件事會互相拆台：
    # 亞洲名額把這些歌塞進前五，曲風名額再把它們換掉——最後兩個下限都掉。
    # 曲風對得上的優先抽，湊不滿再放寬（放寬也比湊不滿好，理由同下）。
    hits = _genre_hit_test(wanted_genres or {})
    tiers = [[r for r in fits if hits(r)], fits] if hits else [fits]

    picked: List[Dict] = []
    for tier in [*tiers, rows]:
        if len(picked) >= want:
            break
        taken = {row["recco_id"] for row in picked}
        picked += seed_pool.draw([r for r in tier if r["recco_id"] not in taken],
                                 vector, ranker.similarity, want=want - len(picked),
                                 region="", center=center)
    return picked


async def _asia_candidates(vector: Dict[str, float], want: int, center: float,
                           constraints: Constraints,
                           wanted_genres: Optional[Dict[str, float]] = None) -> List[Dict]:
    """補一批「一定是亞洲」的候選進候選池。

    為什麼要補：推薦端點回來的候選跟種子幾乎無關，實測 179 首裡只有 7 首是
    亞洲發行（3.9%，NOTES #46）。換種子、換提示詞都動不了這個數字，
    因為那個數字不是我們的排序造成的，是候選池本來就沒有亞洲歌。

    補進來的歌**不享有任何加分**：它們帶著自己的特徵進池子，跟其他候選
    一起被 Discovery Ranker 用同一把尺量。這一步只負責「池子裡有東西可選」，
    選不選得上仍然由分數決定。

    center 是這一次的探索帶帶心。挑候選要照它挑，不是照「最像」挑——
    理由見 seed_pool.draw；constraints 的用途見 _draw_asia。
    """
    if want <= 0 or get_settings().reccobeats_mode == "stub":
        return []
    pool = seed_pool.load()
    if pool:
        asia = [row for row in pool if row.get("region") == seed_pool.ASIA]
        return [_as_candidate(row)
                for row in _draw_from_pool(asia, vector, want, center, constraints, wanted_genres)]
    log.info("沒有 data/vibe_seeds.json，亞洲候選改為即時解析"
             "（跑 scripts/verify_vibe_seeds.py 可以省掉這一段）")
    rows = await _asia_from_catalog(vector, want, center, constraints, wanted_genres)
    return [_as_candidate(row) for row in rows]


async def _genre_candidates(vector: Dict[str, float], want: int, center: float,
                            constraints: Constraints,
                            wanted_genres: Dict[str, float]) -> List[Dict]:
    """補一批「曲風一定對得上」的候選進候選池。沒有想要的曲風時不補。

    **為什麼非補不可。** 這跟 #46 的亞洲比重是同一件事、同一個結論：
    排序排不出池子裡沒有的東西。推薦端點回來的是全球長尾的隨機切片，
    使用者聽 R&B 時池子裡本來就沒幾首 R&B——實測 42 首候選裡只有 2 首算命中，
    這種情況下**權重調到 1.0、名額調到 4，前五命中數完全不動**。

    而執行期補不出曲風覆蓋率：曲風來自 iTunes，量級是每分鐘約 20 次（NOTES #49）。
    所以要嘛池子裡本來就有同曲風的歌，要嘛就沒有——沒有中間選項。
    我們自己的種子池是唯一可以離線標滿曲風的地方，也是唯一標得出 city_pop 的地方。

    **補進來的歌不享有任何加分**（同 #46 的紀律）：它們帶著自己的特徵與曲風
    進池子，跟其他候選被同一把尺量。這一步只負責「池子裡有東西可選」。

    這裡不分地區——地區名額另有機制，而且亞洲那一份也會照曲風挑
    （見 _draw_from_pool），所以同一首歌可以同時滿足兩個名額。
    """
    if want <= 0 or not wanted_genres or get_settings().reccobeats_mode == "stub":
        return []
    pool = seed_pool.load()
    if not pool:
        # 沒有預解析檔時不現場解析：那要對曲庫打好幾趟，而這是加分路徑。
        # 亞洲那一份有現場解析的後路，是因為地區比重是硬需求。
        log.info("沒有 data/vibe_seeds.json，這一輪不補曲風候選")
        return []

    hits = _genre_hit_test(wanted_genres)
    matched = [row for row in pool if hits(row)]
    if not matched:
        log.info("種子池裡沒有 %s 的曲目，這一輪不補曲風候選",
                 "／".join(genres.label(g) for g in wanted_genres))
        return []

    # **兩區各補一半。** 種子池的亞洲那一區比較大（59 對 39），整池一起抽的話
    # 補進來的同曲風候選幾乎都是亞洲的，接著曲風名額把它們拉進前五，
    # 前五就變成 5/5 亞洲——那正是地區上限當初要擋的「幾乎全部」。
    # 兩區都有同曲風的歌可選，上限才有機會守得住。
    west_want = want // 2
    picked = _draw_from_pool([r for r in matched if r.get("region") == seed_pool.WEST],
                             vector, west_want, center, constraints, wanted_genres)
    taken = {row["recco_id"] for row in picked}
    picked += _draw_from_pool([r for r in matched if r["recco_id"] not in taken],
                              vector, want - len(picked), center, constraints, wanted_genres)
    return [_as_candidate(row) for row in picked]


def _one_artist_each(rows: List[Dict]) -> List[Dict]:
    """補進來的候選裡，同一位歌手只留第一首（保序）。

    種子池一位歌手有好幾首，而注入是**分好幾次抽的**（亞洲一次、曲風的兩區
    各一次）。每一次抽自己內部有去重，跨次卻沒有——實測「聽 lo-fi 的人」
    前五拿到三首 STUTS，就是三次抽都抽到他。

    去重放在這裡而不是各自的抽取裡：那幾次抽本來就該互相不知道對方，
    知道了就得互相傳狀態，而這件事在合併前做一次就好。
    """
    out, seen = [], set()
    for row in rows:
        key = name_key(row.get("artist") or "")
        if key and key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _merge_candidates(base: List[Dict], extra: List[Dict]) -> List[Dict]:
    """把補進來的候選併進候選池，同一首歌只留一份（推薦端點偶爾也會回到同一首）。"""
    seen = {cache_key(c.get("artist", ""), c.get("title", "")) for c in base}
    merged = list(base)
    for candidate in extra:
        key = cache_key(candidate.get("artist", ""), candidate.get("title", ""))
        if key and key not in seen:
            seen.add(key)
            merged.append(candidate)
    return merged


def _quota_for_backups(ranked: List[Dict], constraints: Constraints, settings) -> List[Dict]:
    """備位那幾首也照同樣的比例配名額。

    前段有一首在 YouTube 那關被丟掉時，遞補上來的是備位的第一首。備位若清一色
    不是亞洲，掉一首就少一首，名額守住的只是「排序當下」的比重，不是使用者
    真正拿到的那五首（實測就掉成 1/5）。這一步不動前段，只動備位。
    """
    backup = settings.verify_per_round - settings.return_per_round
    if backup <= 0 or settings.asia_min_per_round <= 0:
        return ranked
    ratio = backup / settings.return_per_round
    head, rest = ranked[:settings.return_per_round], ranked[settings.return_per_round:]
    rest, _ = ranker.region_quota(
        rest, constraints, regions.is_asia,
        round(settings.asia_min_per_round * ratio),
        round(settings.asia_max_per_round * ratio) if settings.asia_max_per_round >= 0 else -1,
        backup,
    )
    return head + rest


def _wanted_genres(intent: Dict, profile: Dict) -> Tuple[Dict[str, float], str]:
    """這一輪要照哪些曲風排，回傳 (曲風→權重, 來源)。來源是 "prompt"／"profile"／""。

    **使用者明講的優先，而且是取代不是相加。** 「今天想聽 citypop」是一句
    覆寫的話——把它跟歌單既有的曲風分布混在一起，等於告訴使用者「你說了，
    但我只聽一半」。沒明講才退回歌單（或氛圍）統計出來的分布。

    明講的曲風權重一律是 1：使用者講了兩種曲風，那就是兩種都要，
    沒有主次可言（他沒說主次，排序就不該替他發明一個）。
    """
    wanted = {slug: 1.0 for slug in (intent.get("genres") or [])}
    if wanted:
        return wanted, "prompt"
    stored = {slug: float(weight) for slug, weight
              in (profile.get("genre_weights") or {}).items() if weight}
    return (stored, "profile") if stored else ({}, "")


async def _tag_genres(rows: List[Dict]) -> int:
    """把曲風標到這批列上，回傳標到幾首。關掉或 stub 模式時一律不對外。

    stub 模式的意思是「完全不對外」，所以這裡跟 _asia_candidates 用同一條規則。
    少了這道閘，內網開發與整份測試都會安靜地打到 iTunes——而且因為 _search
    自己把例外吞掉，看起來只會像「就是比較慢」。
    """
    settings = get_settings()
    if not settings.genre_lookup or settings.reccobeats_mode == "stub":
        return 0
    return await itunes.tag_candidates(rows, limit=settings.genre_lookup_max)


# 「算命中」的門檻。取 0.5 而不是 1.0：R&B 對 neo soul 是 0.85、citypop 對 funk
# 是 0.55，那些都該算命中；但 citypop 對泛泛的 pop 只有 0.4，那不算——
# 使用者要的是那個圈子，不是它的上位分類。
GENRE_HIT = 0.5


def _genre_hit_test(wanted: Dict[str, float]):
    """「這首算不算命中使用者要的曲風」的判斷式。沒有指定曲風時回 None。

    回 None 而不是回一個「永遠 False」的函式：呼叫端要能分辨「沒指定」與
    「指定了但沒命中」——前者不該保留名額，後者要把湊不到這件事講出來。
    """
    if not wanted:
        return None

    def hits(candidate: Dict) -> bool:
        return (genres.genre_fit(wanted, genres.genres_of(candidate)) or 0.0) >= GENRE_HIT
    return hits


# --- /api/recommend ----------------------------------------------------------

async def recommend_stream(repo, quota: QuotaTracker, session_id: str, prompt: str
                           ) -> AsyncGenerator[Tuple[str, Dict], None]:
    """依序 yield (event_name, payload)，對應 §4 的 SSE 事件格式。"""
    settings = get_settings()
    profile = await repo.get_profile(session_id)
    if not profile:
        raise SessionNotFound(session_id)
    # 情境入口的品味向量是推出來的，不是聽出來的——理由的用詞要跟著換（見 llm.explain）
    mood_only = profile.get("source_kind") == "vibe"

    # 1) 理解情境
    intent_raw = _stored_intent(profile, prompt) or await llm.parse_intent(prompt)
    constraints = Constraints(**(intent_raw.get("constraints") or {}))
    band_center, band_width = ranker.exploration_band(
        intent_raw.get("exploration"), settings.band_center, settings.band_width
    )
    label = profile.get("vibe") if mood_only and profile.get("vibe") else _intent_label(intent_raw)
    yield "thinking", {"step": "parse", "label": f"理解情境：{label}"}

    # 2) 取得候選
    # 情境入口的種子是建 session 時挑好的；歌單入口則直接用聽過的那幾首，
    # 曲庫沒收的用代打種子（同一位歌手、特徵最接近的那首）遞補。
    seeds = list(profile.get("seed_ids") or [])[:5] or [
        t.get("recco_id") or t.get("seed_id")
        for t in profile.get("tracks", [])
        if t.get("recco_id") or t.get("seed_id")
    ][:5]
    if not seeds and get_settings().reccobeats_mode != "stub":
        # 推薦端點沒有「照著這支向量找相似曲目」的用法，seeds 是必填的曲目 id。
        # 一首都對不上就真的沒得推薦——這裡照實說，不拿假曲庫充數（NOTES #39）。
        yield "error", {
            "code": "no_seeds",
            "message": ("氛圍讀懂了，但推薦要有一首曲庫裡的歌當起點——這次連備援清單都沒對上，"
                        "多半是 ReccoBeats 暫時連不上。稍後再試，或直接貼一份公開歌單／一首歌。")
            if mood_only else
            ("這份歌單的曲目、連同這些歌手，在 ReccoBeats 曲庫裡都找不到，"
             "沒有推薦種子可用。換一份包含較多國際發行曲目的歌單再試一次。"),
        }
        return
    candidates = await reccobeats.get_recommendations(seeds, limit=50)
    candidates = await _fill_missing_features(repo, candidates)
    wanted_genres, genre_source = _wanted_genres(intent_raw, profile)
    avoid_genres = list(intent_raw.get("avoid_genres") or [])
    # 推薦端點回來的候選幾乎沒有亞洲（實測 3.9%），自己補一份進來（NOTES #46）。
    # 曲風同理、而且更嚴重：42 首候選裡只有 2 首對得上使用者的曲風（NOTES #49）。
    # 兩份都從同一個種子池抽，而且亞洲那一份也照曲風挑，所以會有重疊——
    # _merge_candidates 會去重，重疊反而是好事：一首歌同時滿足兩個名額。
    vector = profile.get("vector") or {}
    injected = await _asia_candidates(vector, settings.asia_candidates,
                                      band_center, constraints, wanted_genres)
    injected += await _genre_candidates(vector, settings.genre_candidates,
                                        band_center, constraints, wanted_genres)
    injected = _one_artist_each(injected)
    candidates = _merge_candidates(candidates, injected)
    heard = {cache_key(t.get("artist", ""), t.get("title", "")) for t in profile.get("tracks", [])}
    candidates = [c for c in candidates
                  if cache_key(c.get("artist", ""), c.get("title", "")) not in heard]
    # 補進來的有幾首真的留在池子裡（跟推薦端點重複、或使用者聽過的都會被剔掉）。
    # 這裡不能用「候選裡有幾首亞洲」代替：推薦端點自己也會給幾首亞洲，
    # 混在一起講就是把別人給的算成自己補的
    # 整池候選標完曲風再排序（補進來的亞洲候選也要一起標到）。查的是歌手、
    # 而且有行程內快取，所以熱機之後這一步幾乎是零請求。
    tagged = await _tag_genres(candidates)

    kept = {cache_key(c.get("artist", ""), c.get("title", "")) for c in candidates}
    added = sum(1 for c in injected if cache_key(c.get("artist", ""), c.get("title", "")) in kept)
    label = f"從 ReccoBeats 取得 {len(candidates) - added} 首候選"
    if added:
        label += f"，另外從種子池補進 {added} 首"
    if wanted_genres:
        # 標到幾首要講出來。曲風那一項只在標得到的候選上作數，
        # 標到的比例太低時「有照曲風排」這句話就不成立（同 #4 的教訓）
        label += f"（{tagged}／{len(candidates)} 首查得到曲風）"
    yield "thinking", {"step": "candidates", "label": label}

    # 3) Discovery Ranking
    ranked, hard_filtered = ranker.rank(
        candidates,
        profile.get("vector") or {},
        constraints,
        seen_artists=profile.get("seen_artists"),
        blacklist=profile.get("blacklist"),
        hard_filter=settings.hard_filter,
        min_pool=settings.return_per_round,
        avoid_genres=avoid_genres,
        center=band_center,
        width=band_width,
        w_band=settings.weight_band,
        w_context=settings.weight_context,
        w_novelty=settings.weight_novelty,
        w_genre=settings.weight_genre,
        wanted_genres=wanted_genres,
        penalty=settings.echo_chamber_penalty,
    )
    # 補進來的亞洲候選若一首都擠不進驗證名單，補了等於沒補——這一步只保下限，
    # 而且只在同一層（通過／未通過硬過濾）裡對調，不會把違反情境的歌拉到前面
    # 名額保在「真的會端出去的那五首」，不是驗證名單的八首：驗證名單後段是備位，
    # 前五首都能播的時候永遠輪不到——名額擺在那裡等於沒擺（實測補了 15 首、前五名 0 首）
    # 有「想要的曲風」時，前五首保一個下限——不管那是使用者明講的，還是從歌單
    # 統計出來的。後者一樣算數：使用者貼了一份清一色 R&B 的歌單，就是講了
    # 「我要 R&B」，只是用歌單講的。沒有任何來源時（_wanted_genres 回空）才不保。
    #
    # 兩個名額連跑，順序與 prefer_keep 都是必要的：曲風先跑、地區後跑，
    # 而地區那一輪要知道「曲風剛剛保下來的別動」，否則後跑的會把先跑的
    # 擠出去，兩個下限互相拆台、最後兩個都不成立。
    # **兩個名額會打架，順序就是優先順序。** 補進來的同曲風候選多半是亞洲的
    # （種子池的亞洲那一區比較大），所以「至少 4 首同曲風」與「至多 2 首亞洲」
    # 常常無法同時成立——實測前五拿到 4 首同曲風之後，地區上限把其中 2 首換掉了。
    #
    # 曲風排在後面，也就是曲風贏。理由是使用者能感覺到的差異：端出四首他從沒
    # 聽過的曲風，比端出四首亞洲的歌更像是推薦壞了。地區上限退成「盡量」——
    # 它本來就是為了擋「幾乎全部都是亞洲」，而不是為了在使用者的品味就是
    # 亞洲曲風時把歌換掉。
    #
    # 曲風那一輪帶著 prefer_keep=is_asia：真的要換人時，先換非亞洲的那幾首，
    # 這樣地區下限在多數情況下還是保得住。
    ranked, _ = ranker.region_quota(
        ranked, constraints, regions.is_asia,
        settings.asia_min_per_round, settings.asia_max_per_round, settings.return_per_round,
        avoid_genres=avoid_genres,
    )
    hits_genre = _genre_hit_test(wanted_genres)
    if hits_genre and settings.genre_min_per_round > 0:
        ranked, _ = ranker.region_quota(
            ranked, constraints, hits_genre,
            settings.genre_min_per_round, -1, settings.return_per_round,
            avoid_genres=avoid_genres, prefer_keep=regions.is_asia,
        )
    # 兩個數字都從**最終**的前段重算。取各自名額的回傳值是錯的：後面那一輪
    # 還會再動前段，先算的那個數字在端出去之前就已經過期了。
    head = ranked[:settings.return_per_round]
    asia_in_head = sum(1 for c in head if regions.is_asia(c))
    genre_in_head = sum(1 for c in head if hits_genre(c)) if hits_genre else 0
    ranked = _quota_for_backups(ranked, constraints, settings)
    # 目前的實作是「分級」不是「全丟」，文案要照實說，否則會在 Demo 現場被戳破
    filter_note = "（違反情境的已排到後段）" if hard_filtered else ""
    genre_note = ""
    if wanted_genres:
        names = "／".join(genres.label(slug) for slug in wanted_genres)
        genre_note = (f"，其中 {genre_in_head} 首命中 {names}" if genre_in_head
                      # 湊不到就要講。安靜地少給，看起來就像曲風那句話沒被讀到
                      else f"，但候選池裡找不到 {names}")
    yield "thinking", {
        "step": "rank",
        "label": f"依 Discovery Score 排序{filter_note}，取前 {settings.verify_per_round} 首驗證"
                 + (f"，其中 {asia_in_head} 首亞洲" if asia_in_head else "") + genre_note,
    }

    # 4) 驗證可播放（丟棄補位在這一層完成，使用者無感）
    resolver = VideoResolver(repo, quota)
    report = await resolver.resolve(ranked)

    # 5) 生成理由並逐首送出
    results: List[Dict] = []
    for candidate in report.resolved:
        reason = await llm.explain(profile.get("vector") or {}, candidate, prompt,
                                   mood_only=mood_only)
        track = TrackResult(
            video_id=candidate.get("video_id", ""),
            title=candidate.get("title", ""),
            artist=candidate.get("artist", ""),
            thumbnail=candidate.get("thumbnail", ""),
            reason=reason,
            features=_display_features(candidate.get("features") or {}),
            genres=sorted(genres.genres_of(candidate)),
            score=candidate["score"] if isinstance(candidate.get("score"), Score)
            else Score(**candidate["score"]),
        )
        payload = json.loads(track.model_dump_json())
        results.append(payload)
        yield "track", payload

    await repo.update_profile(session_id, {"last_round": results, "last_prompt": prompt})
    _log_round(session_id, prompt, intent_raw, results, report)

    yield "done", {
        "returned": len(results),
        "wanted": settings.return_per_round,
        # 補了多少、實際端出幾首亞洲，都要看得見。只在後端調參而不講出來的話，
        # 「比重變了嗎」這個問題永遠只能靠感覺回答（同 #4、#44 的教訓）
        "asia": sum(1 for c in report.resolved[:len(results)] if regions.is_asia(c)),
        # 曲風跟亞洲比重同一個理由要看得見：只在後端調權重而不回報命中數，
        # 「曲風有作用嗎」這個問題永遠只能靠感覺回答
        "genres": [slug for slug in wanted_genres],
        "genre_source": genre_source,
        "genre_hits": (sum(1 for c in report.resolved[:len(results)] if hits_genre(c))
                       if hits_genre else 0),
        "genre_tagged": tagged,
        "seed_source": profile.get("seed_source", "playlist"),
        "dropped": report.dropped,
        "quota_used": await quota.used(),
        "quota_spent": report.quota_spent,
        "cache_hits": report.cache_hits,
        "cache_only": report.cache_only,
        # 湊不滿的原因要傳出去。少給幾首而不說原因，看起來就像推薦引擎壞了
        "search_down": report.search_down,
    }


# --- /api/feedback -----------------------------------------------------------

async def feedback_stream(repo, quota: QuotaTracker, session_id: str, video_id: str, vote: str
                          ) -> AsyncGenerator[Tuple[str, Dict], None]:
    profile = await repo.get_profile(session_id)
    if not profile:
        raise SessionNotFound(session_id)

    last_round = profile.get("last_round") or []
    target = next((t for t in last_round if t.get("video_id") == video_id), None)
    if not target:
        raise SessionNotFound(f"{session_id}/{video_id}")

    vector = ranker.apply_feedback(profile.get("vector") or {}, target.get("features") or {}, vote)
    updates: Dict = {"vector": vector}

    # 曲風偏好也要跟著動。只動向量的話，使用者對著三首 citypop 按 👍，
    # 系統學到的只有「他喜歡這個 energy」——而那正是六個維度分不出來的那件事。
    # 明講過曲風的那一輪不在這裡覆寫：那是使用者這一次的指定，不是長期偏好。
    genre_weights = ranker.apply_genre_feedback(
        profile.get("genre_weights") or {}, target.get("genres") or [], vote)
    if genre_weights != (profile.get("genre_weights") or {}):
        updates["genre_weights"] = genre_weights

    # §5.5 同一位歌手連續兩次 👎 → 進 session 黑名單
    artist_key = (target.get("artist") or "").strip().lower()
    blacklist = list(profile.get("blacklist") or [])
    down_votes = dict(profile.get("down_votes") or {})
    if vote == "down" and artist_key:
        down_votes[artist_key] = down_votes.get(artist_key, 0) + 1
        if down_votes[artist_key] >= 2 and artist_key not in blacklist:
            blacklist.append(artist_key)
    elif vote == "up" and artist_key:
        down_votes.pop(artist_key, None)
    updates.update({"blacklist": blacklist, "down_votes": down_votes})

    yield "profile", {"updated_profile": vector, "blacklist": blacklist,
                      "genres": genre_weights}

    # 用新向量重排「上一輪剩下的候選」，不再打任何外部 API（≈0 配額）
    last_prompt = profile.get("last_prompt") or ""
    intent_raw = _stored_intent(profile, last_prompt) or await llm.parse_intent(last_prompt)
    constraints = Constraints(**(intent_raw.get("constraints") or {}))
    settings = get_settings()
    remaining = [t for t in last_round
                 if t.get("video_id") != video_id
                 and (t.get("artist") or "").strip().lower() not in blacklist]
    wanted_genres, _ = _wanted_genres(intent_raw, {**profile, "genre_weights": genre_weights})
    reranked, _ = ranker.rank(
        remaining, vector, constraints,
        seen_artists=profile.get("seen_artists"),
        blacklist=blacklist,
        hard_filter=False,  # 這一輪的候選已經過濾過，重排不再二次砍
        center=settings.band_center, width=settings.band_width,
        w_band=settings.weight_band, w_context=settings.weight_context,
        w_novelty=settings.weight_novelty, w_genre=settings.weight_genre,
        wanted_genres=wanted_genres, penalty=settings.echo_chamber_penalty,
    )

    payloads = []
    for item in reranked[: settings.return_per_round]:
        payload = dict(item)
        payload["score"] = json.loads(item["score"].model_dump_json())
        payloads.append(payload)
        yield "track", payload

    updates["last_round"] = payloads
    await repo.update_profile(session_id, updates)
    yield "done", {"returned": len(payloads), "quota_used": await quota.used(), "dropped": 0}


# --- 小工具 ------------------------------------------------------------------

async def _fill_missing_features(repo, candidates: List[Dict]) -> List[Dict]:
    budget = RecoveryBudget(get_settings().recovery_max_per_session)
    filled = []
    for candidate in candidates:
        if candidate.get("features"):
            # ReccoBeats 沒有 popularity 欄位。只有 stub 模式才補假值——
            # 真實模式偽造熱門度會直接污染 novelty 計分（見 NOTES #34）。
            if candidate.get("popularity") is None and get_settings().reccobeats_mode == "stub":
                candidate["popularity"] = stub_data.stub_popularity(
                    candidate.get("artist", ""), candidate.get("title", "")
                )
            filled.append(candidate)
            continue
        enriched = await _features_for(repo, candidate.get("artist", ""), candidate.get("title", ""), budget)
        if enriched:
            candidate = {**candidate, **enriched}
            filled.append(candidate)
    return filled


def _stored_intent(profile: Dict, prompt: str) -> Optional[Dict]:
    """建立 session 時解析過的 Intent。同一段文字問第二次只會拿到同一個答案。"""
    if profile.get("intent") and profile.get("intent_prompt") == prompt:
        return profile["intent"]
    return None


def _top_artists(tracks: List[Dict], limit: int = 4) -> List[str]:
    """歌單裡出現最多次的歌手。用來取代前端寫死的假曲風標籤。"""
    counts: Dict[str, int] = {}
    display: Dict[str, str] = {}
    for track in tracks:
        name = (track.get("artist") or "").strip()
        if not name:
            continue
        key = name.lower()
        counts[key] = counts.get(key, 0) + 1
        display.setdefault(key, name)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], display[kv[0]]))
    return [display[key] for key, _ in ordered[:limit]]


def _display_features(features: Dict) -> Dict[str, float]:
    """前端只顯示這四個維度（§3.2 契約）。"""
    keys = ["energy", "valence", "acousticness", "tempo"]
    return {k: round(float(features[k]), 3) for k in keys if features.get(k) is not None}


def _intent_label(intent: Dict) -> str:
    parts = [intent.get("mood"), intent.get("activity")]
    constraints = intent.get("constraints") or {}
    if constraints.get("energy_max") is not None:
        parts.append("低能量")
    if constraints.get("energy_min") is not None:
        parts.append("高能量")
    if constraints.get("tempo_range"):
        low, high = constraints["tempo_range"]
        parts.append(f"{int(low)}–{int(high)} BPM")
    if constraints.get("acousticness_min") is not None:
        parts.append("偏原音")
    label = "、".join(str(p) for p in parts if p)
    return label or "沒有明確限制，以你的歌單為主"


def _log_round(session_id: str, prompt: str, intent: Dict, results: List[Dict], report) -> None:
    """§7：recommendation_logs 降級為 JSON Lines 落檔。"""
    settings = get_settings()
    try:
        os.makedirs(settings.log_dir, exist_ok=True)
        row = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "session_id": session_id,
            "prompt": prompt,
            "intent": intent,
            "returned": [{"video_id": r["video_id"], "artist": r["artist"],
                          "title": r["title"], "score": r["score"]} for r in results],
            "dropped": report.dropped,
            "quota_spent": report.quota_spent,
            "cache_hits": report.cache_hits,
        }
        with open(os.path.join(settings.log_dir, "recommendations.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as error:  # noqa: BLE001 — 落檔失敗不能影響推薦
        log.warning("推薦紀錄寫檔失敗：%s", error)
