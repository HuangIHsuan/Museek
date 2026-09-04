"""多金鑰輪替測試（NOTES #37）。

輪替是刻意加入的行為，因此它的每個分支都要有測試釘住——
尤其「什麼時候換下一把」與「什麼時候才真的熔斷」。
"""
from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.core.quota import QuotaTracker, key_id, pacific_day
from app.db.repository import MemoryRepository
from app.services import youtube

KEYS = ["key-alpha", "key-beta", "key-gamma"]


@pytest.fixture
def repo():
    return MemoryRepository(persist=False)


async def seed(repo, key: str, used: int, tracker=None) -> None:
    """直接寫入用量。tracker 已經讀過的話要強制重讀，模擬別的執行個體寫入。"""
    await repo.add_quota_used(f"{pacific_day()}#{key_id(key)}", used)
    if tracker is not None:
        await tracker.refresh()


def test_key_id_does_not_leak_the_key():
    fingerprint = key_id("super-secret-key")
    assert "super-secret-key" not in fingerprint
    assert len(fingerprint) == 8
    assert key_id("a") != key_id("b")


async def test_settings_parse_comma_separated_keys(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEYS", " k1 , k2 ,k1, ")
    get_settings.cache_clear()
    assert get_settings().youtube_keys == ["k1", "k2"]      # 去空白、去重、保序


async def test_settings_fall_back_to_single_key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEYS", "")
    monkeypatch.setenv("YOUTUBE_API_KEY", "only-one")
    get_settings.cache_clear()
    assert get_settings().youtube_keys == ["only-one"]


async def test_starts_on_the_first_key(repo):
    tracker = QuotaTracker(repo, KEYS)
    assert await tracker.active_key() == "key-alpha"
    assert await tracker.active_index() == 1


async def test_moves_to_next_key_when_one_is_exhausted(repo):
    tracker = QuotaTracker(repo, KEYS)
    await seed(repo, "key-alpha", 10_000)
    assert await tracker.active_key() == "key-beta"
    assert await tracker.active_index() == 2


async def test_mark_exhausted_switches_immediately(repo):
    tracker = QuotaTracker(repo, KEYS)
    await tracker.spend(500)
    assert await tracker.active_key() == "key-alpha"

    await tracker.mark_exhausted("key-alpha")
    assert await tracker.active_key() == "key-beta"
    # 被標記耗盡的那把要記到上限，不能只是跳過——重啟後才不會又用它
    detail = {row["key"]: row for row in await tracker.breakdown()}
    assert detail[key_id("key-alpha")]["used"] == 10_000
    assert detail[key_id("key-alpha")]["exhausted"] is True


async def test_active_key_is_none_when_all_exhausted(repo):
    tracker = QuotaTracker(repo, KEYS)
    for k in KEYS:
        await seed(repo, k, 10_000)
    assert await tracker.active_key() is None
    assert await tracker.active_index() == 0
    assert await tracker.can_spend(100) is False


async def test_spend_lands_on_the_active_key(repo):
    tracker = QuotaTracker(repo, KEYS)
    await seed(repo, "key-alpha", 10_000)
    await tracker.spend(300)
    detail = {row["key"]: row["used"] for row in await tracker.breakdown()}
    assert detail[key_id("key-alpha")] == 10_000
    assert detail[key_id("key-beta")] == 300      # 花在目前這一把上
    assert detail[key_id("key-gamma")] == 0


async def test_totals_span_every_key(repo):
    tracker = QuotaTracker(repo, KEYS)
    await seed(repo, "key-alpha", 4_000)
    await seed(repo, "key-beta", 1_000)
    assert await tracker.used() == 5_000
    assert await tracker.limit() == 30_000        # 三把各 10,000


async def test_circuit_breaker_needs_every_key_over_the_line(repo):
    """只有一把過門檻不能熔斷——還有別把可以用。"""
    tracker = QuotaTracker(repo, KEYS)
    await seed(repo, "key-alpha", 8_000, tracker)
    assert await tracker.cache_only() is False

    await seed(repo, "key-beta", 8_000, tracker)
    assert await tracker.cache_only() is False

    await seed(repo, "key-gamma", 8_000, tracker)
    assert await tracker.cache_only() is True


async def test_no_keys_means_stub_not_exhausted(repo):
    """沒設定任何金鑰＝走 stub，不該被當成配額用盡。"""
    tracker = QuotaTracker(repo, [])
    assert await tracker.cache_only() is False
    assert await tracker.can_spend(100) is True


async def test_breakdown_marks_exactly_one_active(repo):
    tracker = QuotaTracker(repo, KEYS)
    await seed(repo, "key-alpha", 10_000)
    rows = await tracker.breakdown()
    assert [r["active"] for r in rows] == [False, True, False]
    assert all("key-" not in r["key"] for r in rows)   # 只有指紋，沒有金鑰本身


async def test_refresh_picks_up_writes_from_another_instance(repo):
    """多個執行個體各記各的話會一起超花——重讀必須看得到對方寫入的用量。"""
    tracker = QuotaTracker(repo, KEYS)
    assert await tracker.used() == 0                 # 先讀一次，建立快取

    await seed(repo, "key-alpha", 9_000)             # 模擬另一個執行個體花掉
    await tracker.refresh()

    assert await tracker.used() == 9_000
    assert await tracker.active_key() == "key-alpha"  # 9,000 < 10,000，還沒滿


def test_search_quota_exhaustion_is_recognised_from_a_429(monkeypatch):
    """search.list 用完當日次數時 Google 回 429 + rateLimitExceeded，不是 403。

    只認 403 的話熔斷不會跳、金鑰不會換，整輪推薦會被當成「每首都查不到」。
    """
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                      "errors": [{"reason": "rateLimitExceeded"}]}}
    request = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/search")
    response = httpx.Response(429, json=body, request=request)
    error = httpx.HTTPStatusError("429", request=request, response=response)

    assert youtube._quota_error(error) is True

    not_quota = httpx.Response(400, json={"error": {"errors": [{"reason": "badRequest"}]}},
                               request=request)
    assert youtube._quota_error(
        httpx.HTTPStatusError("400", request=request, response=not_quota)) is False
