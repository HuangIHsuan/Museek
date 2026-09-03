"""外部服務的 stub 資料源（§2.2：所有外部服務的 stub 實作，讓整條流程在內網端到端跑通）。

特徵值由「歌手|歌名」雜湊決定，因此同一首歌每次都拿到同一組數字——
stub 模式下的排序結果是可重現的，Demo 演練與單元測試才有意義。
"""
from __future__ import annotations

import hashlib
from typing import Dict, List

from app.core.normalize import cache_key

_STUB_LIBRARY = [
    ("Frank Ocean", "White Ferrari"), ("Frank Ocean", "Self Control"),
    ("Bon Iver", "Holocene"), ("Bon Iver", "re: Stacks"),
    ("Cigarettes After Sex", "Apocalypse"), ("Beach House", "Space Song"),
    ("Radiohead", "Weird Fishes"), ("Sufjan Stevens", "Mystery of Love"),
    ("Nujabes", "Feather"), ("Tom Misch", "Movie"),
    ("落日飛車 Sunset Rollercoaster", "My Jinji"), ("告五人", "唯一"),
    ("deca joins", "浴室"), ("陳綺貞", "魚"), ("盧廣仲", "刻在我心底的名字"),
    ("茄子蛋", "浪子回頭"), ("草東沒有派對", "大風吹"), ("HYUKOH", "Comes And Goes"),
    ("Se So Neon", "Go Back"), ("IU", "Through the Night"),
    ("YOASOBI", "群青"), ("Fujii Kaze", "Shinunoga E-Wa"),
    ("Mac DeMarco", "Chamber of Reflection"), ("Men I Trust", "Show Me How"),
    ("Khruangbin", "August 10"), ("Men I Trust", "Numb"),
    ("Clairo", "Bags"), ("Rex Orange County", "Sunflower"),
    ("Daniel Caesar", "Best Part"), ("SZA", "Good Days"),
    ("Phoebe Bridgers", "Motion Sickness"), ("The xx", "Intro"),
    ("Weyes Blood", "Andromeda"), ("Alvvays", "Archie, Marry Me"),
    ("Still Woozy", "Goodie Bag"), ("Yellow Days", "Your Hand Holding Mine"),
    ("Homeshake", "Every Single Thing"), ("Crumb", "Locket"),
    ("Slowdive", "Sugar for the Pill"), ("Cocteau Twins", "Cherry-coloured Funk"),
]


def _digest(artist: str, title: str) -> List[int]:
    raw = hashlib.sha256(cache_key(artist, title).encode("utf-8")).digest()
    return list(raw)


def stub_features(artist: str, title: str) -> Dict[str, float]:
    d = _digest(artist, title)
    return {
        "energy": round(d[0] / 255, 3),
        "valence": round(d[1] / 255, 3),
        "danceability": round(d[2] / 255, 3),
        "acousticness": round(d[3] / 255, 3),
        "instrumentalness": round(d[4] / 255 * 0.6, 3),
        "liveness": round(d[5] / 255 * 0.5, 3),
        "loudness": round(-24 + d[6] / 255 * 22, 2),
        "speechiness": round(d[7] / 255 * 0.4, 3),
        "tempo": round(60 + d[8] / 255 * 100, 1),
    }


def stub_popularity(artist: str, title: str) -> int:
    return int(_digest(artist, title)[9] / 255 * 100)


def stub_recco_id(artist: str, title: str) -> str:
    return "stub-" + hashlib.sha1(cache_key(artist, title).encode("utf-8")).hexdigest()[:16]


def stub_video_id(artist: str, title: str) -> str:
    """穩定的 11 碼假 videoId。stub 模式播不出來是預期的——播放要走外網真實資料。"""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    digest = _digest(artist, title)
    return "".join(alphabet[b % len(alphabet)] for b in digest[:11])


def stub_catalog() -> List[Dict]:
    """stub 版 ReccoBeats 曲庫，推薦與歌單解析共用。"""
    catalog = []
    for artist, title in _STUB_LIBRARY:
        catalog.append({
            "recco_id": stub_recco_id(artist, title),
            "artist": artist,
            "title": title,
            "features": stub_features(artist, title),
            "popularity": stub_popularity(artist, title),
        })
    return catalog
