"""把 Museek 變成一支「掃 QR 就能裝到 iPhone 主畫面」的假 app。

這裡只做三件事：
  1. 猜出手機該連的網址（部署網域 → 用它；本機開發 → 用區網 IP）
  2. 把那串網址畫成 QR
  3. 排一張安裝說明頁

真正讓它「像 app」的是 index.html 的 apple-mobile-web-app-* meta、
manifest 的 display:standalone，以及 sw.js。這支只負責把人帶到那一頁。
"""
from __future__ import annotations

import socket
from urllib.parse import urlsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


def lan_ip() -> str | None:
    """本機在區網裡的 IPv4。

    連一個外部位址、問 socket 自己用了哪張網卡——UDP 不會真的送出封包，
    所以離線也不會卡住。抓不到就回 None（例如完全沒有網路介面）。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def is_local_host(host: str) -> bool:
    """host 是不是 localhost 那一類（手機連不到的位址）。"""
    return host.split(":")[0].strip("[]").lower() in {h.strip("[]") for h in LOCAL_HOSTS}


def _http_url(value: str | None) -> str | None:
    """只放行 http/https。QR 會被人直接掃著開，不能變成任意 scheme 的跳板。"""
    if not value:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme in {"http", "https"} and parts.netloc:
        return value.strip().rstrip("/")
    return None


def guess_install_url(
    *, host: str, scheme: str, override: str | None = None, configured: str | None = None
) -> tuple[str, str]:
    """回傳 (手機該開的網址, 這個網址怎麼來的)。

    優先序：?url= 手動指定 → PUBLIC_BASE_URL 設定 → 目前的對外網域 → 區網 IP。
    設定值排在網域前面，是為了讓本機開發時掃到的也是線上版。
    """
    manual = _http_url(override)
    if manual:
        return manual, "manual"

    fixed = _http_url(configured)
    if fixed:
        return fixed, "configured"

    # 已經是對外網域（Cloud Run、ngrok…）：手機直接連同一個位址就好
    if host and not is_local_host(host):
        return f"{scheme}://{host}", "origin"

    ip = lan_ip()
    if ip is None:
        return "", "none"
    port = host.split(":")[-1] if ":" in host else "8000"
    return f"http://{ip}:{port}", "lan"


def qr_svg(url: str) -> str | None:
    """把網址畫成內嵌 SVG。沒裝 segno 就回 None，頁面自己會退成純文字。

    有兩個地方非補不可，少一個掃出來就是壞的：

    * **viewBox**：segno 只給 width/height，不給 viewBox。那種 SVG 被 CSS 縮放
      （`width:100%`）不是縮小，是**裁切**——右邊與下面的定位點會整個不見。
      看起來還很像一張 QR，但相機讀不到東西。
    * **quiet zone 4 模組**：規格要求的留白，別再調小。

    另外關掉反鋸齒（crispEdges）：模組邊緣糊掉會讓相機在小尺寸下對不準。
    """
    try:
        import segno
    except ModuleNotFoundError:
        return None
    import io
    import re

    buf = io.BytesIO()
    segno.make(url, error="m").save(
        buf,
        kind="svg",
        scale=8,
        border=4,
        dark="#14140f",
        light="#fbfbf9",
        xmldecl=False,
        svgns=True,
        svgclass=None,
        lineclass=None,
        nl=False,
    )
    svg = buf.getvalue().decode("utf-8")

    size = re.search(r'<svg[^>]*\bwidth="(\d+(?:\.\d+)?)"', svg)
    if size:
        svg = svg.replace(
            "<svg ",
            f'<svg viewBox="0 0 {size.group(1)} {size.group(1)}" shape-rendering="crispEdges" ',
            1,
        )
    return svg


def qr_terminal(url: str) -> str | None:
    """終端機版 QR（給啟動腳本印的）。"""
    try:
        import segno
    except ModuleNotFoundError:
        return None
    import io

    buf = io.StringIO()
    segno.make(url, error="m").terminal(out=buf, border=2)
    return buf.getvalue()


_PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>把 Museek 裝到手機 | Museek</title>
<style>
  :root {{
    --paper:#f2f1ec; --card:#fbfbf9; --ink:#14140f; --muted:#5c5b52;
    --rule:rgba(20,20,15,.18); --lime:#b6f414; --accent:#e8009c;
    --display:Arial Black,"Noto Sans TC",system-ui,sans-serif;
    --body:"Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif;
    --mono:Consolas,"SFMono-Regular",monospace;
  }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; min-height:100dvh; background:var(--paper); color:var(--ink);
         font-family:var(--body); line-height:1.6; padding:40px 20px }}
  body::before {{ content:""; position:fixed; inset:0; z-index:-1; opacity:.22;
    background-image:linear-gradient(var(--rule) 1px,transparent 1px),linear-gradient(90deg,var(--rule) 1px,transparent 1px);
    background-size:44px 44px }}
  .wrap {{ width:min(100%,880px); margin:0 auto }}
  .eyebrow {{ font:700 12px/1 var(--mono); letter-spacing:.18em; text-transform:uppercase; color:var(--muted) }}
  h1 {{ font:900 clamp(34px,6vw,54px)/1.05 var(--display); letter-spacing:-.04em; margin:14px 0 8px }}
  h1 em {{ font-style:normal; color:var(--accent) }}
  .lede {{ margin:0 0 30px; max-width:52ch; color:var(--muted) }}
  .grid {{ display:grid; grid-template-columns:auto 1fr; gap:30px; align-items:start }}
  .qr {{ border:1px solid var(--ink); background:var(--card); padding:18px; box-shadow:7px 7px 0 var(--ink); line-height:0 }}
  .qr svg {{ display:block; width:min(260px,60vw); height:auto }}
  .url {{ margin-top:14px; font:13px/1.5 var(--mono); word-break:break-all; text-align:center; max-width:260px }}
  ol {{ margin:0; padding-left:22px }}
  li {{ margin-bottom:14px }}
  .kbd {{ display:inline-block; border:1px solid var(--ink); border-radius:3px; padding:1px 7px;
          background:var(--card); font:700 13px var(--mono) }}
  .note {{ margin-top:34px; border-left:3px solid var(--lime); padding:2px 0 2px 15px; color:var(--muted); font-size:14px }}
  .warn {{ border:1px solid var(--ink); background:var(--card); padding:18px; box-shadow:5px 5px 0 var(--ink) }}
  code {{ font:13px var(--mono); background:var(--card); border:1px solid var(--rule); padding:1px 5px }}
  a {{ color:var(--ink) }}
  @media (max-width:700px) {{ .grid {{ grid-template-columns:1fr }} .qr svg {{ width:min(300px,72vw) }} }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="eyebrow">Install on iPhone</div>
    <h1>把 Museek 裝成<em>一支 app</em></h1>
    <p class="lede">用 iPhone 相機掃右邊的 QR，網頁開起來之後加到主畫面。之後從主畫面點開，
      沒有網址列、沒有分頁列，跟原生 app 幾乎一樣。</p>
    {body}
    <div class="note">{note}</div>
  </div>
</body>
</html>
"""

_STEPS = """<div class="grid">
      <div>
        <div class="qr">{qr}</div>
        <div class="url">{url}</div>
      </div>
      <ol>
        <li><b>用 iPhone 內建「相機」掃這個 QR</b>，點畫面上跳出的連結。<br>
          （手機要跟這台電腦連同一個 Wi-Fi。）</li>
        <li>頁面開起來後，點 Safari 底部中間的<span class="kbd">分享</span>鍵
          （方框加上箭頭那個）。</li>
        <li>往下滑，選<span class="kbd">加入主畫面</span>，右上角按<span class="kbd">新增</span>。</li>
        <li>回主畫面，點那顆 Museek 圖示——它會全螢幕開啟，看不出來是網頁。</li>
      </ol>
    </div>"""

_NO_URL = """<div class="warn">
      <b>抓不到可以給手機連的網址。</b><br>
      請在網址後面自己指定，例如
      <code>/install?url=http://192.168.1.23:8000</code>。
    </div>"""


def render_install_page(url: str, source: str) -> str:
    """組出安裝說明頁。url 為空字串時只給補救指示。"""
    if not url:
        return _PAGE.format(body=_NO_URL, note="找不到區網 IP：這台機器可能沒有連上任何網路。")

    svg = qr_svg(url)
    qr = svg if svg else f'<div style="font:13px monospace;line-height:1.5;padding:20px">{url}</div>'
    notes = {
        "lan": "這是區網網址，只有跟這台電腦同一個 Wi-Fi 的手機連得到，離開就打不開了。"
               "區網用的是 http://，所以 Service Worker（離線快取）不會啟用——功能不受影響。"
               "要給外面的人用，請部署到 HTTPS 網域，再從那個網域開這一頁。",
        "origin": "這是目前這個網域的網址，手機在任何網路下都連得到。",
        "manual": "這是你自己指定的網址（?url=）。",
        "configured": "這是 PUBLIC_BASE_URL 指定的正式網址，手機在任何網路下都連得到。",
    }
    return _PAGE.format(body=_STEPS.format(qr=qr, url=url), note=notes.get(source, ""))
