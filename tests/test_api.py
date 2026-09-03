"""端到端測試：全程走 stub，不對外連線、不燒任何配額。"""
from __future__ import annotations

import json
from typing import Dict, List, Tuple

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def parse_sse(text: str) -> List[Tuple[str, Dict]]:
    events = []
    for chunk in text.strip().split("\n\n"):
        if not chunk.strip():
            continue
        name, payload = "message", {}
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:])
        events.append((name, payload))
    return events


async def make_session(client) -> str:
    response = await client.post("/api/session",
                                 json={"playlist_url": "https://www.youtube.com/playlist?list=PLdemo"})
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


async def test_session_returns_profile_and_match_counts(client):
    response = await client.post("/api/session",
                                 json={"playlist_url": "https://www.youtube.com/playlist?list=PLdemo"})
    data = response.json()
    assert response.status_code == 200
    assert data["session_id"]
    assert data["matched"] > 0
    assert set(data["profile"]["vector"]) >= {"energy", "valence", "tempo"}
    assert all(0 <= v <= 1 for k, v in data["profile"]["vector"].items() if k != "tempo")


async def test_session_accepts_single_video_url(client):
    response = await client.post("/api/session",
                                 json={"playlist_url": "https://youtu.be/IwxkGdhkAGU"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["session_id"]
    assert data["matched"] + data["unmatched"] == 1


async def test_session_falls_back_to_video_when_mix_playlist(client):
    # watch?v=...&list=RD... 是自動混音清單，讀不到歌單也要能用單曲建立品味
    response = await client.post("/api/session", json={
        "playlist_url": "https://www.youtube.com/watch?v=IwxkGdhkAGU&list=RDIwxkGdhkAGU"
    })
    assert response.status_code == 200, response.text
    assert response.json()["matched"] + response.json()["unmatched"] == 1


async def test_session_rejects_non_youtube_url(client):
    response = await client.post("/api/session", json={"playlist_url": "https://example.com/list?list=PL1"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_url"
    assert len(response.json()["detail"]["hint"]) == 3   # 三組示範歌單退路


async def test_private_playlist_offers_demo_playlists(client):
    response = await client.post("/api/session",
                                 json={"playlist_url": "https://www.youtube.com/playlist?list=PLprivate"})
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "playlist_not_accessible"
    assert "示範歌單" in detail["message"]


async def test_recommend_streams_thinking_then_tracks_then_done(client):
    session_id = await make_session(client)
    response = await client.post("/api/recommend", json={
        "session_id": session_id, "prompt": "下雨天開車想放空，類似我平常聽的但不要太吵"
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]

    assert names.count("thinking") >= 3
    assert names[-1] == "done"
    assert "error" not in names

    steps = [payload["step"] for name, payload in events if name == "thinking"]
    assert steps[:3] == ["parse", "candidates", "rank"]

    tracks = [payload for name, payload in events if name == "track"]
    assert 1 <= len(tracks) <= 5
    for track in tracks:
        assert track["video_id"] and track["title"] and track["artist"]
        assert track["reason"]
        assert set(track["score"]) == {"similarity", "band", "context_fit", "novelty", "final"}

    done = events[-1][1]
    assert "dropped" in done and "quota_used" in done   # Demo 最後五秒要用


async def test_recommend_respects_the_do_not_be_loud_constraint(client):
    """使用者說了「不要太吵」，回傳的曲目 energy 不該炸出來（§5.4 硬過濾）。"""
    session_id = await make_session(client)
    response = await client.post("/api/recommend", json={
        "session_id": session_id, "prompt": "下雨天開車想放空，不要太吵"
    })
    tracks = [p for name, p in parse_sse(response.text) if name == "track"]
    assert tracks
    assert all(t["features"]["energy"] <= 0.5 for t in tracks)


async def test_recommend_with_unknown_session_emits_error_event(client):
    response = await client.post("/api/recommend", json={"session_id": "nope", "prompt": "隨便"})
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "session_not_found"


async def test_feedback_moves_profile_and_reranks(client):
    session_id = await make_session(client)
    recommend = await client.post("/api/recommend",
                                  json={"session_id": session_id, "prompt": "放鬆一點的音樂"})
    tracks = [p for name, p in parse_sse(recommend.text) if name == "track"]
    assert len(tracks) >= 2
    before = (await client.get("/api/health")).status_code
    assert before == 200

    response = await client.post("/api/feedback", json={
        "session_id": session_id, "video_id": tracks[0]["video_id"], "vote": "down"
    })
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "profile"
    assert names[-1] == "done"

    updated = events[0][1]["updated_profile"]
    session_vector = (await client.get("/api/health")).json()
    assert isinstance(updated, dict) and updated

    reranked = [p for name, p in parse_sse(response.text) if name == "track"]
    assert all(t["video_id"] != tracks[0]["video_id"] for t in reranked)  # 被 👎 的不再出現


async def test_health_reports_four_dependencies_and_quota(client):
    response = await client.get("/api/health")
    data = response.json()
    assert response.status_code == 200
    assert set(data) >= {"youtube", "reccobeats", "llm", "mongo", "quota_used", "quota_limit", "cache_only"}
    assert data["youtube"] == "stub"          # 沒設金鑰就不該偷打 YouTube
    assert data["quota_used"] == 0            # stub 模式不燒配額
    assert data["quota_limit"] == 10000


async def test_blacklist_accumulates_across_two_down_votes(client):
    """直接餵一份含同歌手兩首的 last_round，驗證連兩次 👎 的黑名單累計。"""
    from app.db.repository import get_repository

    repo = await get_repository()
    round_payload = [
        {"video_id": f"vid{i}", "title": f"Song {i}", "artist": "Loud Band" if i < 2 else f"Other {i}",
         "thumbnail": "", "reason": "", "features": {"energy": 0.5, "valence": 0.5, "tempo": 100},
         "score": {"similarity": 0.8, "band": 0.5, "context_fit": 1.0, "novelty": 0.5, "final": 0.6}}
        for i in range(4)
    ]
    await repo.save_profile({
        "session_id": "fixed", "playlist_id": "PL", "tracks": [],
        "vector": {"energy": 0.5, "valence": 0.5, "tempo": 100},
        "popularity_mean": 50, "seen_artists": [], "blacklist": [], "down_votes": {},
        "last_round": round_payload, "last_prompt": "放鬆", "created_at": None, "expires_at": None,
    })

    first = await client.post("/api/feedback",
                              json={"session_id": "fixed", "video_id": "vid0", "vote": "down"})
    assert parse_sse(first.text)[0][1]["blacklist"] == []

    second = await client.post("/api/feedback",
                               json={"session_id": "fixed", "video_id": "vid1", "vote": "down"})
    events = parse_sse(second.text)
    assert events[0][1]["blacklist"] == ["loud band"]
    assert all(p["artist"] != "Loud Band" for name, p in events if name == "track")
