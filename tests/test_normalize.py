"""曲名正規化與網址解析測試。測資之後由 T 補到 100 筆真實樣本。"""
from __future__ import annotations

import pytest

from app.core.normalize import (
    InvalidPlaylistUrl,
    artist_variants,
    cache_key,
    clean_title,
    extract_playlist_id,
    split_artist_title,
)

SAMPLES = [
    ("Frank Ocean - White Ferrari (Official Audio)", None, "Frank Ocean", "White Ferrari"),
    ("【MV】告五人 Accusefive - 唯一 Only", None, "告五人 Accusefive", "唯一 Only"),
    ("IU(아이유) _ Love wins all M/V", None, "IU", "Love wins all"),
    ("周杰倫 Jay Chou【告白氣球 Love Confession】Official MV", None, "周杰倫 Jay Chou", "告白氣球 Love Confession"),
    ("White Ferrari", "Frank Ocean - Topic", "Frank Ocean", "White Ferrari"),
    ("YOASOBI「アイドル」 Official Music Video", None, "YOASOBI", "アイドル"),
    ("Radiohead - Weird Fishes/ Arpeggi [Lyrics]", None, "Radiohead", "Weird Fishes/ Arpeggi"),
    ("茄子蛋EggPlantEgg -【浪子回頭 Waves Wandering】Official Music Video", None, "茄子蛋EggPlantEgg", "浪子回頭 Waves Wandering"),
    ("Tyler, The Creator - EARFQUAKE (Lyrics) 🎵", None, "Tyler, The Creator", "EARFQUAKE"),
    ("Beyoncé - Halo (Official Video) #shorts", None, "Beyoncé", "Halo"),
]


@pytest.mark.parametrize("raw,channel,artist,title", SAMPLES)
def test_split_artist_title(raw, channel, artist, title):
    assert split_artist_title(raw, channel) == (artist, title)


def test_clean_title_strips_feat():
    assert clean_title("Song Name (feat. Someone Else)") == "Song Name"


def test_cache_key_is_case_and_space_insensitive():
    assert cache_key("Frank  OCEAN ", " White Ferrari") == cache_key("frank ocean", "white ferrari")
    assert cache_key("Frank Ocean", "White Ferrari") == "frank ocean|white ferrari"


def test_cache_key_keeps_cjk_and_hangul():
    assert cache_key("告五人", "唯一") == "告五人|唯一"


def test_artist_variants_splits_bilingual_names():
    assert artist_variants("周杰倫 Jay Chou") == ["周杰倫 Jay Chou", "Jay Chou", "周杰倫"]
    assert artist_variants("Radiohead") == ["Radiohead"]


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/playlist?list=PLabc123", "PLabc123"),
    ("https://music.youtube.com/playlist?list=OLAK5uy_x&si=1", "OLAK5uy_x"),
    ("youtube.com/watch?v=abc&list=PL999", "PL999"),
])
def test_extract_playlist_id(url, expected):
    assert extract_playlist_id(url) == expected


@pytest.mark.parametrize("url", [
    "",
    "https://example.com/playlist?list=PLabc",       # 網域白名單（合規檢核表）
    "https://www.youtube.com/watch?v=abc",           # 沒有 list 參數
    "javascript:alert(1)//youtube.com?list=PLabc",   # 非 http(s)
])
def test_rejected_playlist_urls(url):
    with pytest.raises(InvalidPlaylistUrl):
        extract_playlist_id(url)
