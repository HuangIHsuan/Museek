"""曲名正規化與網址解析測試。測資之後由 T 補到 100 筆真實樣本。"""
from __future__ import annotations

import pytest

from app.core.normalize import (
    InvalidPlaylistUrl,
    artist_variants,
    cache_key,
    clean_title,
    extract_playlist_id,
    parse_source,
    same_artist,
    same_title,
    split_artist_title,
    title_variants,
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
    # ft 黏在單字裡（Soft）不能被當成 feat. 標記
    ("Soft Lipa - 給我一點時間 Official Music Video", "SoftLipaOfficial", "Soft Lipa", "給我一點時間"),
    # 方括號裡是歌名（官方頻道的寫法），不是雜訊
    ("告五人 Accusefive [ 唯一 Only ] Official Music Video", "告五人 Accusefive",
     "告五人 Accusefive", "唯一 Only"),
    # 沒有分隔符、歌手名直接黏在歌名前面
    ("【HYBS】Tip Toe (Official Video)", "HYBS", "HYBS", "Tip Toe"),
    # 引號包住的才是歌名，頻道名（HYBE LABELS）不是歌手
    ("NewJeans (뉴진스) 'Super Shy' Official MV", "HYBE LABELS", "NewJeans", "Super Shy"),
    # 全形方括號的雜訊標記
    ("Official髭男dism - Pretender［Official Video］", "Official髭男dism",
     "Official髭男dism", "Pretender"),
    # 撇號要留著：清成「That s What I Like」就對不上任何一個曲庫
    ("Bruno Mars - That's What I Like [Official Music Video]", "Bruno Mars",
     "Bruno Mars", "That's What I Like"),
    # 方括號裡是版本標記時，它不是歌名
    ("Song Name [Remix]", "Some Channel", "Some Channel", "Song Name Remix"),
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


def test_title_variants_splits_bilingual_titles():
    # YouTube 上是「魚 Fish」，iTunes 與曲庫多半只收其中一種寫法
    assert title_variants("魚 Fish") == ["魚 Fish", "Fish", "魚"]
    assert title_variants("唯一 (三立戲劇插曲)") == ["唯一 (三立戲劇插曲)", "唯一"]
    assert title_variants("White Ferrari") == ["White Ferrari"]


@pytest.mark.parametrize("wanted,found", [
    ("魚 Fish", "魚"),                                   # 曲庫只收中文名
    ("大風吹 Simon Says", "Simon Says"),                  # 美國商店只收英文名
    ("唯一 Only", "唯一 (三立/台視戲劇《戀愛是科學》插曲)"),   # 對方多帶了戲劇標記
])
def test_same_title_matches_across_bilingual_forms(wanted, found):
    assert same_title(wanted, found)


def test_same_title_still_rejects_a_different_song():
    assert not same_title("魚 Fish", "魚仔")
    assert not same_title("唯一 Only", "唯二")


def test_same_artist_tolerates_store_transliterations():
    # iTunes TW 把 Official髭男dism 寫成 Official鬍子男dism
    assert same_artist("Official髭男dism", "Official鬍子男dism")
    # 但只差一兩個字才算，「告五人」不能配到「五月天」身上
    assert not same_artist("告五人 Accusefive", "五月天")
    assert not same_artist("Frank Ocean", "Frank Sinatra")


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
    "https://www.youtube.com/watch?v=abc",           # v 不是合法的 11 碼影片 ID
    "javascript:alert(1)//youtube.com?list=PLabc",   # 非 http(s)
])
def test_rejected_playlist_urls(url):
    with pytest.raises(InvalidPlaylistUrl):
        extract_playlist_id(url)


@pytest.mark.parametrize("url,kind,expected", [
    ("https://www.youtube.com/playlist?list=PLabc123", "playlist", "PLabc123"),
    ("https://www.youtube.com/watch?v=IwxkGdhkAGU", "video", "IwxkGdhkAGU"),
    ("https://youtu.be/IwxkGdhkAGU?si=xyz", "video", "IwxkGdhkAGU"),
    ("https://www.youtube.com/shorts/IwxkGdhkAGU", "video", "IwxkGdhkAGU"),
    ("music.youtube.com/watch?v=IwxkGdhkAGU", "video", "IwxkGdhkAGU"),
    # 一般歌單優先於單曲
    ("https://www.youtube.com/watch?v=IwxkGdhkAGU&list=PL999", "playlist", "PL999"),
    # 自動混音清單（RD 開頭）讀不到 playlistItems，直接當單曲
    ("https://www.youtube.com/watch?v=IwxkGdhkAGU&list=RDIwxkGdhkAGU", "video", "IwxkGdhkAGU"),
])
def test_parse_source(url, kind, expected):
    source = parse_source(url)
    assert (source.kind, source.id) == (kind, expected)


def test_parse_source_keeps_video_fallback_for_playlist_urls():
    source = parse_source("https://www.youtube.com/watch?v=IwxkGdhkAGU&list=PL999")
    assert source.video_id == "IwxkGdhkAGU"


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=abc",           # 影片 ID 不是 11 碼
    "https://www.youtube.com/feed/subscriptions",    # 既沒有歌單也沒有影片
])
def test_parse_source_rejects_non_music_urls(url):
    with pytest.raises(InvalidPlaylistUrl):
        parse_source(url)
