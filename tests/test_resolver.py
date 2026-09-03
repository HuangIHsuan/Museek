"""Video Resolver 測試（§8 配額控管、§9 丟棄補位）。

這一層決定會不會燒掉當日配額，因此每條路徑都要有測試：
快取命中不花點數、丟棄要補位、熔斷後只用快取、單輪搜尋次數有上限。
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.core.normalize import cache_key
from app.core.quota import QuotaTracker, key_id, pacific_day

TEST_KEY = "test-key-never-real"   # 與 conftest 的 YOUTUBE_API_KEY 一致
from app.core.resolver import VideoResolver
from app.db.repository import MemoryRepository
from app.services import youtube


@pytest.fixture(autouse=True)
def live_youtube(monkeypatch):
    """假裝有金鑰讓配額計數跑起來。search_video 一律由各測試 monkeypatch 掉，
    因此不會有任何真實呼叫——這把假 key 是刻意的，不能換成真的。"""
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-never-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def candidates(count: int):
    return [{"artist": f"Artist {i}", "title": f"Song {i}", "features": {}, "popularity": 50}
            for i in range(count)]


async def seed_quota(repo, used: int, key: str = TEST_KEY) -> None:
    """灌入某把金鑰的當日用量。文件 id 是「日期#金鑰指紋」，每把各記各的。"""
    await repo.add_quota_used(f"{pacific_day()}#{key_id(key)}", used)


async def test_cache_hits_cost_nothing(monkeypatch):
    repo = MemoryRepository(persist=False)
    for item in candidates(5):
        await repo.set_video(cache_key(item["artist"], item["title"]),
                             {"video_id": "cached", "title": item["title"],
                              "channel": item["artist"], "thumbnail": "", "embeddable": True})

    async def fail(*_args, **_kwargs):
        raise AssertionError("已有快取就不該呼叫 search.list")

    monkeypatch.setattr(youtube, "search_video", fail)
    report = await VideoResolver(repo, QuotaTracker(repo)).resolve(candidates(5))

    assert len(report.resolved) == 5
    assert report.cache_hits == 5
    assert report.quota_spent == 0
    assert report.searches == 0


async def test_unfindable_candidates_are_dropped_and_backfilled(monkeypatch):
    """查不到的候選丟掉並補下一名，使用者拿到的仍是五首（防幻覺機制）。"""
    async def search(artist, title, api_key=None):
        return None if title in ("Song 0", "Song 2") else {
            "video_id": f"vid-{title}", "title": title, "channel": artist,
            "thumbnail": "", "embeddable": True,
        }

    monkeypatch.setattr(youtube, "search_video", search)
    repo = MemoryRepository(persist=False)
    report = await VideoResolver(repo, QuotaTracker(repo)).resolve(candidates(8))

    assert len(report.resolved) == 5
    assert report.dropped == 2
    assert all("Song 0" not in t["title"] and "Song 2" not in t["title"] for t in report.resolved)


async def test_unembeddable_results_are_dropped(monkeypatch):
    async def search(artist, title, api_key=None):
        return {"video_id": "v", "title": title, "channel": artist,
                "thumbnail": "", "embeddable": title != "Song 1"}

    monkeypatch.setattr(youtube, "search_video", search)
    repo = MemoryRepository(persist=False)
    report = await VideoResolver(repo, QuotaTracker(repo)).resolve(candidates(8))
    assert report.dropped == 1


async def test_a_dropped_candidate_is_remembered_so_we_never_pay_twice(monkeypatch):
    calls = []

    async def search(artist, title, api_key=None):
        calls.append(title)
        return None

    monkeypatch.setattr(youtube, "search_video", search)
    repo = MemoryRepository(persist=False)
    quota = QuotaTracker(repo)
    await VideoResolver(repo, quota).resolve(candidates(1))
    await VideoResolver(repo, quota).resolve(candidates(1))
    assert calls == ["Song 0"]  # 第二輪讀快取，不再花 100 點


async def test_searches_are_capped_per_round(monkeypatch):
    async def search(artist, title, api_key=None):
        return None  # 全部查不到，逼它一路往下找

    monkeypatch.setattr(youtube, "search_video", search)
    repo = MemoryRepository(persist=False)
    report = await VideoResolver(repo, QuotaTracker(repo)).resolve(candidates(40), budget=8)

    assert report.searches == 8                     # §8：單輪最多驗證 8 首
    assert report.quota_spent == 800


async def test_circuit_breaker_switches_to_cache_only(monkeypatch):
    """當日用量過門檻後只回快取內已有 videoId 的候選（§9 配額耗盡降級）。"""
    async def fail(*_args, **_kwargs):
        raise AssertionError("熔斷後不該再呼叫 search.list")

    monkeypatch.setattr(youtube, "search_video", fail)
    repo = MemoryRepository(persist=False)
    await seed_quota(repo, 8000)
    await repo.set_video(cache_key("Artist 3", "Song 3"),
                         {"video_id": "cached", "title": "Song 3", "channel": "Artist 3",
                          "thumbnail": "", "embeddable": True})

    report = await VideoResolver(repo, QuotaTracker(repo)).resolve(candidates(8))

    assert report.cache_only is True
    assert len(report.resolved) == 1                # 曲目池較小，但仍可播放
    assert report.quota_spent == 0


async def test_quota_exceeded_from_youtube_stops_further_searches(monkeypatch):
    calls = []

    async def search(artist, title, api_key=None):
        calls.append(title)
        raise youtube.QuotaExceeded("quota")

    monkeypatch.setattr(youtube, "search_video", search)
    repo = MemoryRepository(persist=False)
    report = await VideoResolver(repo, QuotaTracker(repo)).resolve(candidates(8))

    assert len(calls) == 1                          # 收到 403 就不再往下打
    assert report.cache_only is True
    assert report.resolved == []


async def test_resolver_stops_once_it_has_enough(monkeypatch):
    calls = []

    async def search(artist, title, api_key=None):
        calls.append(title)
        return {"video_id": f"vid-{title}", "title": title, "channel": artist,
                "thumbnail": "", "embeddable": True}

    monkeypatch.setattr(youtube, "search_video", search)
    repo = MemoryRepository(persist=False)
    report = await VideoResolver(repo, QuotaTracker(repo)).resolve(candidates(20), want=5)

    assert len(calls) == 5                          # 湊滿就收手，不多花 1,500 點
    assert report.quota_spent == 500
