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
from app.core.normalize import cache_key, extract_playlist_id, split_artist_title
from app.core.quota import QuotaTracker
from app.core.resolver import VideoResolver
from app.db.repository import profile_expiry
from app.models import Constraints, Score, TrackResult
from app.services import llm, reccobeats, stub_data, youtube

log = logging.getLogger("museek.pipeline")


class SessionNotFound(Exception):
    pass


# --- 特徵取得（feature_cache 優先，非 YouTube 來源可長期保留）------------------

async def _features_for(repo, artist: str, title: str) -> Optional[Dict]:
    """取得單曲特徵。feature_cache 優先，未命中才對外查。

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
            return {"recco_id": row.get("recco_id"), "features": row.get("features") or {},
                    "popularity": row.get("popularity")}

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
    if not recco_id:
        return None
    features = (await reccobeats.get_audio_features([recco_id])).get(recco_id)
    if not features:
        return None
    payload = {"recco_id": recco_id, "features": features,
               "popularity": None, "source": "reccobeats"}
    await repo.set_features(key, payload)
    return payload


# --- /api/session ------------------------------------------------------------

async def create_session(repo, quota: QuotaTracker, playlist_url: str) -> Dict:
    settings = get_settings()
    playlist_id = extract_playlist_id(playlist_url)

    # 歌單讀取也走輪替：一把耗盡就換下一把。stub 模式沒有金鑰，直接呼叫。
    if not youtube.is_live():
        items = await youtube.fetch_playlist_items(playlist_id)
    else:
        items, used_key = None, None
        while items is None:
            used_key = await quota.active_key()
            if used_key is None:
                raise youtube.QuotaExceeded("所有 YouTube 金鑰的當日配額都已用盡")
            try:
                items = await youtube.fetch_playlist_items(playlist_id, api_key=used_key)
            except youtube.QuotaExceeded:
                await quota.mark_exhausted(used_key)
        await quota.spend(settings.quota_cost_playlist_items, key=used_key)

    tracks: List[Dict] = []
    for item in items:
        artist, title = split_artist_title(item.get("raw_title", ""), item.get("channel"))
        if not title:
            continue
        enriched = await _features_for(repo, artist, title)
        tracks.append({
            "raw_title": item.get("raw_title", ""),
            "artist": artist,
            "title": title,
            "recco_id": (enriched or {}).get("recco_id"),
            "features": (enriched or {}).get("features") or {},
            "popularity": (enriched or {}).get("popularity"),
            "matched": bool(enriched),
        })

    vector, popularity_mean, seen_artists, matched, unmatched, warning = profiler.build_profile(tracks)
    session_id = uuid.uuid4().hex

    await repo.save_profile({
        "session_id": session_id,
        "playlist_id": playlist_id,
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
    seeds = [t["recco_id"] for t in profile.get("tracks", []) if t.get("recco_id")][:5]
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
        enriched = await _features_for(repo, candidate.get("artist", ""), candidate.get("title", ""))
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
