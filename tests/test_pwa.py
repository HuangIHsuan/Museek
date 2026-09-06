"""安裝頁與 PWA 外殼：確認手機掃到的網址是對的，且 Service Worker 不會碰 /api。"""
from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.pwa import guess_install_url, qr_svg


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def test_public_host_wins_over_lan_ip():
    """已經是對外網域時，QR 要指向那個網域，而不是連不到的區網 IP。"""
    assert guess_install_url(host="museek.example.com", scheme="https") == (
        "https://museek.example.com",
        "origin",
    )


def test_localhost_falls_back_to_lan_ip():
    """localhost 手機連不到，要換成區網 IP，並沿用同一個埠。"""
    url, source = guess_install_url(host="localhost:8000", scheme="http")
    if source == "none":
        pytest.skip("這台機器沒有區網 IP")
    assert source == "lan"
    assert re.fullmatch(r"http://\d+\.\d+\.\d+\.\d+:8000", url), url


def test_configured_url_beats_the_lan_ip():
    """設了 PUBLIC_BASE_URL：本機開發時掃到的也要是線上版，不是區網 IP。"""
    assert guess_install_url(
        host="localhost:8000", scheme="http",
        configured="https://museek.example.com/",
    ) == ("https://museek.example.com", "configured")


def test_manual_override_still_beats_the_configured_url():
    """?url= 是臨時指定，要壓過設定值。"""
    url, source = guess_install_url(
        host="localhost:8000", scheme="http",
        override="http://192.168.1.9:8000", configured="https://museek.example.com",
    )
    assert (url, source) == ("http://192.168.1.9:8000", "manual")


def test_a_junk_configured_url_falls_through_instead_of_being_used():
    """設定值填壞了就當作沒設，不能讓 QR 掃出一個怪東西。"""
    assert guess_install_url(host="museek.example.com", scheme="https",
                             configured="museek.example.com")[1] == "origin"


def test_override_only_accepts_http_urls():
    """?url= 不能變成任意 scheme 的跳板。"""
    assert guess_install_url(host="localhost:8000", scheme="http",
                             override="https://demo.example.com")[1] == "manual"
    assert guess_install_url(host="localhost:8000", scheme="http",
                             override="javascript:alert(1)")[1] != "manual"


def test_qr_is_inline_svg_without_xml_declaration():
    """QR 要能直接塞進 HTML，所以不能帶 XML 宣告。"""
    svg = qr_svg("https://museek.example.com")
    assert svg is not None
    assert svg.lstrip().startswith("<svg")


def test_qr_has_a_viewbox_so_css_scales_it_instead_of_cropping_it():
    """沒有 viewBox 的 SVG 被 `width:100%` 縮小時是裁切，不是縮放。

    切掉的是右邊與下面的定位點——畫面上看起來還是一張 QR，但完全掃不出東西。
    彈窗與 /install 兩處都會縮放它，所以這個屬性一定要在。
    """
    svg = qr_svg("https://museek-628708623127.asia-east1.run.app")
    assert 'viewBox="0 0 328 328"' in svg
    assert 'width="328"' in svg  # viewBox 與 width 要一致，比例才不會歪


def test_qr_keeps_the_four_module_quiet_zone():
    """規格要求的留白。33 模組的版本 4 + 兩邊各 4 = 41，乘 scale 8 = 328。"""
    svg = qr_svg("https://museek-628708623127.asia-east1.run.app")
    assert 'width="328"' in svg


async def test_install_page_renders_qr(client):
    response = await client.get("/install")
    assert response.status_code == 200
    assert "加入主畫面" in response.text
    assert "<svg" in response.text


async def test_service_worker_is_served_at_root_scope(client):
    """SW 放在 /static/ 底下只能管 /static/，一定要從根路徑供應。"""
    response = await client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["service-worker-allowed"] == "/"
    assert "javascript" in response.headers["content-type"]


async def test_service_worker_never_intercepts_the_sse_endpoint(client):
    """推薦是 SSE 長連線，被 SW 攔下來就會斷。"""
    body = (await client.get("/sw.js")).text
    assert 'url.pathname.startsWith("/api/")' in body
    assert 'request.method !== "GET"' in body


async def test_index_declares_the_ios_app_shell(client):
    """iOS 靠這幾個 meta 判斷要不要全螢幕開啟。"""
    html = (await client.get("/")).text
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    assert "viewport-fit=cover" in html
    assert 'rel="manifest"' in html
    assert "env(safe-area-inset-top)" in html


async def test_install_info_endpoint_carries_url_and_qr(client):
    """導覽列彈窗只打這一支，它要一次給齊網址、來源與畫好的 QR。"""
    response = await client.get("/api/install", headers={"host": "museek.example.com",
                                                         "x-forwarded-proto": "https"})
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://museek.example.com"
    assert body["source"] == "origin"
    assert body["qr_svg"].lstrip().startswith("<svg")


async def test_install_info_is_never_cached(client):
    """換了 Wi-Fi、IP 變了，不能還掃到上一次那張 QR。"""
    response = await client.get("/api/install")
    assert response.headers["cache-control"] == "no-store"


async def test_nav_has_a_qr_entry_wired_to_the_dialog(client):
    html = (await client.get("/")).text
    assert 'id="qr-nav"' in html
    assert 'id="qr-overlay"' in html
    assert '$("qr-nav").addEventListener("click", openQrDialog)' in html
