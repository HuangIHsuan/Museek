"""對部署好的服務跑一輪端到端檢查。

用法：  .venv/bin/python scripts/smoke_test.py <BASE_URL> [歌單網址]

刻意設計成「不燒配額也能跑完大部分」：只有推薦那一步會用到 search.list，
而且會把實際花費印出來。
"""
from __future__ import annotations

import json
import sys
import time

import httpx

DEFAULT_PLAYLIST = "https://www.youtube.com/playlist?list=UU4eYXhJI4-7wSWc8UNRwD4A"
PROMPT = "下雨天開車想放空，類似我平常聽的但不要太吵"

passed = failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✓ {label}" + (f"  {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  ✗ {label}  {detail}")


def read_sse(client: httpx.Client, path: str, body: dict, base: str) -> list:
    events = []
    with client.stream("POST", f"{base}{path}", json=body, timeout=300) as response:
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append([line[6:].strip(), None])
            elif line.startswith("data:") and events:
                events[-1][1] = json.loads(line[5:])
    return [(name, payload) for name, payload in events if payload is not None]


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765").rstrip("/")
    playlist = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PLAYLIST
    client = httpx.Client(follow_redirects=True)
    print(f"目標：{base}\n")

    print("[1] 健康檢查")
    t = time.time()
    health = client.get(f"{base}/api/health", timeout=60)
    check("HTTP 200", health.status_code == 200, f"{(time.time()-t):.1f}s")
    if health.status_code != 200:
        print(health.text[:300]); return 1
    h = health.json()
    print(f"      {json.dumps(h, ensure_ascii=False)}")
    check("四個依賴都有回報", all(k in h for k in ("youtube", "reccobeats", "llm", "mongo")))
    check("配額未熔斷", not h.get("cache_only"), f"已用 {h.get('quota_used')}/{h.get('quota_limit')}")
    quota_before = h.get("quota_used", 0)

    print("\n[2] 前端頁面")
    page = client.get(f"{base}/", timeout=60)
    check("首頁載得到", page.status_code == 200)
    check("是 Museek 的頁面", "Museek" in page.text)
    check("manifest 存在", client.get(f"{base}/static/manifest.webmanifest", timeout=30).status_code == 200)

    print("\n[3] 錯誤處理")
    bad = client.post(f"{base}/api/session", json={"playlist_url": "https://example.com/x?list=PL1"}, timeout=60)
    check("非 YouTube 網址被擋", bad.status_code == 400,
          bad.json().get("detail", {}).get("code", "") if bad.status_code == 400 else str(bad.status_code))
    missing = client.post(f"{base}/api/session",
                          json={"playlist_url": "https://www.youtube.com/playlist?list=DEMO001"}, timeout=60)
    check("無效歌單回友善錯誤（非 500）", missing.status_code == 404,
          f"HTTP {missing.status_code}")
    if missing.status_code == 404:
        check("附帶示範歌單退路", len(missing.json()["detail"].get("hint") or []) == 3)

    print("\n[4] 解析歌單")
    t = time.time()
    session = client.post(f"{base}/api/session", json={"playlist_url": playlist}, timeout=180)
    check("HTTP 200", session.status_code == 200, f"{(time.time()-t):.1f}s")
    if session.status_code != 200:
        print(session.text[:400]); return 1
    data = session.json()
    sid = data["session_id"]
    check("有 session_id", bool(sid))
    check("有品味向量", bool(data["profile"]["vector"]), json.dumps(data["profile"]["vector"], ensure_ascii=False))
    check("有比對統計", data["matched"] + data["unmatched"] > 0,
          f"收錄 {data['matched']} / 未收錄 {data['unmatched']}")

    print("\n[5] 推薦串流")
    t = time.time()
    events = read_sse(client, "/api/recommend", {"session_id": sid, "prompt": PROMPT}, base)
    names = [n for n, _ in events]
    check("沒有 error 事件", "error" not in names,
          str([p for n, p in events if n == "error"]) if "error" in names else "")
    check("thinking 步驟 ≥ 3", names.count("thinking") >= 3)
    check("最後是 done", names and names[-1] == "done", f"{(time.time()-t):.1f}s")
    tracks = [p for n, p in events if n == "track"]
    check("有回傳曲目", len(tracks) > 0, f"{len(tracks)} 首")
    for track in tracks[:1]:
        check("曲目欄位完整",
              all(track.get(k) for k in ("video_id", "title", "artist", "reason")))
        check("score 五個欄位齊全",
              set(track.get("score", {})) == {"similarity", "band", "context_fit", "novelty", "final"})
    if tracks:
        print(f"      例：{tracks[0]['artist']} - {tracks[0]['title']}")
        print(f"          {tracks[0]['reason']}")
    if names and names[-1] == "done":
        done = events[-1][1]
        check("done 有 dropped 與 quota_used", "dropped" in done and "quota_used" in done,
              json.dumps(done, ensure_ascii=False))

    print("\n[6] 回饋重排")
    if tracks:
        fb = read_sse(client, "/api/feedback",
                      {"session_id": sid, "video_id": tracks[0]["video_id"], "vote": "down"}, base)
        fnames = [n for n, _ in fb]
        check("先送 profile 事件", fnames and fnames[0] == "profile")
        check("最後是 done", fnames and fnames[-1] == "done")
        if fnames and fnames[0] == "profile":
            check("品味向量有更新", bool(fb[0][1].get("updated_profile")),
                  json.dumps(fb[0][1]["updated_profile"], ensure_ascii=False))
        reranked = [p for n, p in fb if n == "track"]
        check("被 👎 的不再出現", all(t["video_id"] != tracks[0]["video_id"] for t in reranked),
              f"重排後 {len(reranked)} 首")

    print("\n[7] 配額結算")
    after = client.get(f"{base}/api/health", timeout=60).json()
    spent = after.get("quota_used", 0) - quota_before
    check("配額花費有記錄", spent >= 0, f"本次花費 {spent} 點，累計 {after.get('quota_used')}")

    print(f"\n{'='*44}\n通過 {passed} 項、失敗 {failed} 項")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
