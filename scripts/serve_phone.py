#!/usr/bin/env python3
"""在區網啟動 Museek，並直接在終端機印出手機掃的 QR。

    .venv/bin/python scripts/serve_phone.py          # 預設 8000 埠
    .venv/bin/python scripts/serve_phone.py --port 8080

跟 `uvicorn app.main:app` 的差別只有兩件事：綁 0.0.0.0（手機才連得到），
以及開跑前把網址與 QR 印出來。安裝步驟在 http://<區網 IP>:<port>/install。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.pwa import lan_ip, qr_terminal  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="在區網啟動 Museek 並印出手機用的 QR")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="改程式碼自動重啟")
    parser.add_argument("--lan", action="store_true",
                        help="就算設了 PUBLIC_BASE_URL，也印區網網址（要掃本機這一份時用）")
    args = parser.parse_args()

    public = get_settings().public_base_url.strip().rstrip("/")
    ip = lan_ip()
    if public and not args.lan:
        url = public
    elif ip is None:
        print("⚠️  抓不到區網 IP：這台機器好像沒連上網路。手機將連不到這個服務。")
        url = f"http://localhost:{args.port}"
    else:
        url = f"http://{ip}:{args.port}"

    qr = qr_terminal(url)
    print()
    if qr:
        print(qr)
    else:
        print("（沒裝 segno，印不出 QR：pip install segno）")
    print(f"  手機掃上面的 QR，或直接開：{url}")
    print(f"  加到主畫面的圖解步驟：      {url}/install")
    if public and not args.lan:
        print("  這是 PUBLIC_BASE_URL 的正式網址——掃到的是線上版，不是這一台。")
        print(f"  要掃本機這一份請加 --lan（本機位址：http://{ip or 'localhost'}:{args.port}）。")
    else:
        print("  手機要跟這台電腦連同一個 Wi-Fi。")
    print("  Ctrl+C 結束。\n")
    sys.stdout.flush()  # uvicorn 的 log 走 stderr，不 flush 的話 QR 會被緩衝壓到後面

    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
