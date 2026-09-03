"""網址解析與曲名正規化。純字串處理，內網可完整開發與測試（§1.1）。"""
from __future__ import annotations

import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

# --- 歌單網址 ---------------------------------------------------------------

ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be", "www.youtu.be",
}


class InvalidPlaylistUrl(ValueError):
    pass


def extract_playlist_id(url: str) -> str:
    """從 YouTube 網址萃取 playlistId。合規要求：僅接受 youtube.com／youtu.be 網域。"""
    raw = (url or "").strip()
    if not raw:
        raise InvalidPlaylistUrl("請貼上 YouTube 歌單連結。")
    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise InvalidPlaylistUrl("只接受 http／https 連結。")
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise InvalidPlaylistUrl("只接受 youtube.com 或 youtu.be 的歌單連結。")

    playlist_id = parse_qs(parsed.query).get("list", [None])[0]
    if not playlist_id:
        raise InvalidPlaylistUrl("這個連結沒有歌單 ID，請用「分享 → 複製連結」貼上整份歌單。")
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", playlist_id):
        raise InvalidPlaylistUrl("歌單 ID 格式不正確。")
    return playlist_id


# --- 曲名正規化 -------------------------------------------------------------

# 括號雜訊：官方 MV／歌詞影片／畫質標記／現場版等
_BRACKET_NOISE = re.compile(
    r"""[\(\[\{【（〔]\s*
        (?:[^)\]\}】）〕]*?
           (?:official|lyric|lyrics|mv|m/v|music\s*video|audio|visualizer|video|
              hd|hq|full|4k|1080p|720p|remaster(?:ed)?|explicit|clean|
              live|cover|acoustic|instrumental|karaoke|teaser|trailer|
              動態歌詞|中文歌詞|中字|歌詞|字幕|完整版|官方|高畫質|中文翻譯|純享版)
           [^)\]\}】）〕]*?)
        \s*[\)\]\}】）〕]""",
    re.IGNORECASE | re.VERBOSE,
)

# 無括號的尾綴雜訊
_TAIL_NOISE = re.compile(
    r"\s*[-–—|｜/]\s*(?:official\s*(?:music\s*)?video|official\s*audio|"
    r"lyric[s]?\s*video|music\s*video|mv|audio|topic|"
    r"官方(?:完整)?(?:版|音檔|影音)?|動態歌詞|中文歌詞)\s*$",
    re.IGNORECASE,
)

# 沒有分隔符、單純黏在字尾的雜訊（例：「... 'DDU-DU' M/V」「... Official MV」）
_BARE_TAIL_NOISE = re.compile(
    r"(?:\s+|(?<=[\]\)】》」』]))(?:official\s*)?"
    r"(?:m/v|mv|music\s*video|lyric[s]?\s*video|official\s*audio|"
    r"official\s*video|visualizer|audio|hd|hq|4k|1080p|720p|完整版|官方版)\s*$",
    re.IGNORECASE,
)

_FEAT = re.compile(r"\s*[\(\[]?\s*(?:feat\.?|ft\.?|featuring|with)\s+[^)\]]*[\)\]]?\s*", re.IGNORECASE)
_HASHTAG = re.compile(r"(?:^|\s)#\S+")
_EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "←-⇿" "⬀-⯿" "]+"
)
_QUOTES = re.compile(r"[“”‘’\"']")
_STRAY_BRACKETS = re.compile(r"[「」『』《》〈〉【】]")
_MULTISPACE = re.compile(r"\s+")

# 「歌手 - 歌名」的常見分隔符
# 冒號分隔（「Mon Rovîa: Tiny Desk Concert」「宇多田ヒカル：First Love」）放在最後，
# 因為歌名本身含冒號的機率高於前面幾種分隔符。
_SPLITTERS = [" - ", " – ", " — ", " _ ", " / ", "｜", " | ", ": ", "："]

# 「歌手【歌名】」「歌手《歌名》」「歌手「歌名」」——中文／日韓圈常見寫法，
# 括號內是歌名而不是雜訊，必須在切分前優先辨認。
_TITLE_IN_BRACKET = re.compile(r"^(.{1,40}?)\s*[「《【](.+?)[」》】]\s*$")


def clean_title(raw: str) -> str:
    """去掉 YouTube 曲名裡的行銷雜訊，保留歌手與歌名。"""
    text = _EMOJI.sub(" ", raw or "")
    text = _HASHTAG.sub(" ", text)
    for _ in range(3):  # 巢狀／連續括號需要多跑幾輪
        new = _BRACKET_NOISE.sub(" ", text)
        if new == text:
            break
        text = new
    text = _TAIL_NOISE.sub("", text)
    for _ in range(2):
        new = _BARE_TAIL_NOISE.sub("", text)
        if new == text:
            break
        text = new
    text = _FEAT.sub(" ", text)
    text = _QUOTES.sub(" ", text)
    text = text.strip(" -–—|｜/·、,")
    return _MULTISPACE.sub(" ", text).strip()


def split_artist_title(raw_title: str, channel: Optional[str] = None) -> Tuple[str, str]:
    """回傳 (artist, title)。切不出歌手時退回頻道名（去掉 " - Topic" 等後綴）。"""
    cleaned = clean_title(raw_title)

    match = _TITLE_IN_BRACKET.match(cleaned)
    if match and match.group(1).strip():
        return _tidy_artist(match.group(1)), clean_title(match.group(2))

    for splitter in _SPLITTERS:
        if splitter in cleaned:
            left, right = cleaned.split(splitter, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return _tidy_artist(left), clean_title(right)

    fallback_artist = _tidy_artist(
        clean_title(re.sub(r"\s*-\s*Topic$", "", channel or "", flags=re.IGNORECASE))
    )
    return fallback_artist, _MULTISPACE.sub(" ", _STRAY_BRACKETS.sub(" ", cleaned)).strip()


_PAREN_TAIL = re.compile(r"\s*[\(（\[【][^)）\]】]*[\)）\]】]\s*$")


def _tidy_artist(value: str) -> str:
    """去掉歌手名後面的譯名括號：IU(아이유) → IU。"""
    text = _PAREN_TAIL.sub("", (value or "").strip())
    text = text.strip(" -–—|｜/_·、,:：")
    return text or (value or "").strip()


def artist_variants(artist: str) -> list:
    """歌手名可能是「中文名 英文名」並列，回傳可用於外部搜尋的候選寫法（去重、保序）。"""
    text = (artist or "").strip()
    if not text:
        return []
    variants = [text]
    latin = " ".join(re.findall(r"[A-Za-z0-9&\.\'-]+", text)).strip()
    non_latin = _MULTISPACE.sub(" ", re.sub(r"[A-Za-z0-9&\.\'-]+", " ", text)).strip()
    for candidate in (latin, non_latin):
        if len(candidate) >= 2 and candidate not in variants:
            variants.append(candidate)
    return variants


def cache_key(artist: str, title: str) -> str:
    """video_cache 的 _id：正規化後的「歌手|歌名」（§6）。"""
    def norm(value: str) -> str:
        value = _MULTISPACE.sub(" ", (value or "").lower().strip())
        return re.sub(r"[^\w一-鿿가-힯぀-ヿ ]+", "", value).strip()
    return "{}|{}".format(norm(artist), norm(title))
