"""把各模組串成 /api/session 與 /api/recommend 的實際流程。"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from app.config import get_settings
from app.core import profiler, ranker
from app.core.normalize import cache_key, name_key, parse_source, split_artist_title
from app.core.quota import QuotaTracker
from app.core.resolver import VideoResolver
from app.db.repository import profile_expiry
from app.models import Constraints, Score, TrackResult
from app.services import itunes, llm, reccobeats, stub_data, youtube

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


async def _proxy_seed(artist_names: List[str], features: Dict[str, float]) -> Optional[str]:
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
    log.info("代打種子：%s（相似度 %.3f，原曲不在曲庫）", best["title"], best_score)
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
                        budget: Optional[RecoveryBudget] = None) -> Optional[Dict]:
    """取得單曲特徵。feature_cache 優先，未命中才對外查。

    對外查有兩條路：先查 ReccoBeats 曲庫，查不到才用試聽片段做音訊分析。
    兩者的特徵是同一個尺度，可以混在同一支向量裡（NOTES #38）。

    快取項目會標記來源。從 stub 切到真實模式時，**舊的 stub 假特徵絕對不能再取用**——
    否則真實模式會端出一整份看起來正常、實際上是雜湊亂數的品味向量（NOTES #35）。
    """
    stub_mode = get_settings().reccobeats_mode == "stub"
    key = cache_key(artist, title)
    cached = await repo.get_features([key])
    if key in cached:
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
    for item in items:
        artist, title = split_artist_title(item.get("raw_title", ""), item.get("channel"))
        if not title:
            continue
        enriched = await _features_for(repo, artist, title, budget)
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

    vector, popularity_mean, seen_artists, matched, unmatched, warning = profiler.build_profile(tracks)
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
        "seen_artists": seen_artists,
        "blacklist": [],
        "down_votes": {},          # 歌手 → 連續 👎 次數
        "last_round": [],          # 上一輪回傳的候選，回饋重排時要用
        "last_prompt": "",
        "created_at": datetime.now(tz=timezone.utc),
        "expires_at": profile_expiry(),
    })

    return {
        "session_id": session_id,
        "profile": {"vector": vector, "popularity_mean": popularity_mean, "warning": warning,
                    "top_artists": _top_artists(tracks)},
        "matched": matched,
        "unmatched": unmatched,
        # 其中幾首的特徵是靠試聽片段分析出來的，不是曲庫查到的——這件事要看得見
        "analyzed": analyzed,
    }


# --- /api/recommend ----------------------------------------------------------

async def recommend_stream(repo, quota: QuotaTracker, session_id: str, prompt: str
                           ) -> AsyncGenerator[Tuple[str, Dict], None]:
    """依序 yield (event_name, payload)，對應 §4 的 SSE 事件格式。"""
    settings = get_settings()
    profile = await repo.get_profile(session_id)
    if not profile:
        raise SessionNotFound(session_id)

    # 1) 理解情境
    intent_raw = await llm.parse_intent(prompt)
    constraints = Constraints(**(intent_raw.get("constraints") or {}))
    band_center, band_width = ranker.exploration_band(
        intent_raw.get("exploration"), settings.band_center, settings.band_width
    )
    yield "thinking", {"step": "parse", "label": f"理解情境：{_intent_label(intent_raw)}"}

    # 2) 取得候選
    # 曲庫沒收的那幾首用代打種子（同一位歌手、特徵最接近的那首）遞補
    seeds = [t.get("recco_id") or t.get("seed_id")
             for t in profile.get("tracks", [])
             if t.get("recco_id") or t.get("seed_id")][:5]
    if not seeds and get_settings().reccobeats_mode != "stub":
        # 推薦端點沒有「照著這支向量找相似曲目」的用法，seeds 是必填的曲目 id。
        # 一首都對不上就真的沒得推薦——這裡照實說，不拿假曲庫充數（NOTES #39）。
        yield "error", {
            "code": "no_seeds",
            "message": "這份歌單的曲目、連同這些歌手，在 ReccoBeats 曲庫裡都找不到，"
                       "沒有推薦種子可用。換一份包含較多國際發行曲目的歌單再試一次。",
        }
        return
    candidates = await reccobeats.get_recommendations(seeds, limit=50)
    candidates = await _fill_missing_features(repo, candidates)
    heard = {cache_key(t.get("artist", ""), t.get("title", "")) for t in profile.get("tracks", [])}
    candidates = [c for c in candidates
                  if cache_key(c.get("artist", ""), c.get("title", "")) not in heard]
    yield "thinking", {"step": "candidates", "label": f"從 ReccoBeats 取得 {len(candidates)} 首候選"}

    # 3) Discovery Ranking
    ranked, hard_filtered = ranker.rank(
        candidates,
        profile.get("vector") or {},
        constraints,
        seen_artists=profile.get("seen_artists"),
        blacklist=profile.get("blacklist"),
        hard_filter=settings.hard_filter,
        min_pool=settings.return_per_round,
        center=band_center,
        width=band_width,
        w_band=settings.weight_band,
        w_context=settings.weight_context,
        w_novelty=settings.weight_novelty,
        penalty=settings.echo_chamber_penalty,
    )
    # 目前的實作是「分級」不是「全丟」，文案要照實說，否則會在 Demo 現場被戳破
    filter_note = "（違反情境的已排到後段）" if hard_filtered else ""
    yield "thinking", {
        "step": "rank",
        "label": f"依 Discovery Score 排序{filter_note}，取前 {settings.verify_per_round} 首驗證",
    }

    # 4) 驗證可播放（丟棄補位在這一層完成，使用者無感）
    resolver = VideoResolver(repo, quota)
    report = await resolver.resolve(ranked)

    # 5) 生成理由並逐首送出
    results: List[Dict] = []
    for candidate in report.resolved:
        reason = await llm.explain(profile.get("vector") or {}, candidate, prompt)
        track = TrackResult(
            video_id=candidate.get("video_id", ""),
            title=candidate.get("title", ""),
            artist=candidate.get("artist", ""),
            thumbnail=candidate.get("thumbnail", ""),
            reason=reason,
            features=_display_features(candidate.get("features") or {}),
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
        "dropped": report.dropped,
        "quota_used": await quota.used(),
        "quota_spent": report.quota_spent,
        "cache_hits": report.cache_hits,
        "cache_only": report.cache_only,
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

    yield "profile", {"updated_profile": vector, "blacklist": blacklist}

    # 用新向量重排「上一輪剩下的候選」，不再打任何外部 API（≈0 配額）
    constraints = Constraints(**((await llm.parse_intent(profile.get("last_prompt") or "")).get("constraints") or {}))
    settings = get_settings()
    remaining = [t for t in last_round
                 if t.get("video_id") != video_id
                 and (t.get("artist") or "").strip().lower() not in blacklist]
    reranked, _ = ranker.rank(
        remaining, vector, constraints,
        seen_artists=profile.get("seen_artists"),
        blacklist=blacklist,
        hard_filter=False,  # 這一輪的候選已經過濾過，重排不再二次砍
        center=settings.band_center, width=settings.band_width,
        w_band=settings.weight_band, w_context=settings.weight_context,
        w_novelty=settings.weight_novelty, penalty=settings.echo_chamber_penalty,
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
