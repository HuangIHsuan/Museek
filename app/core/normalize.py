"""網址解析與曲名正規化。純字串處理，內網可完整開發與測試（§1.1）。"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import NamedTuple, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# --- 歌單／單曲網址 ---------------------------------------------------------------

ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be", "www.youtu.be",
}


class InvalidPlaylistUrl(ValueError):
    pass


class Source(NamedTuple):
    """使用者貼進來的連結解析結果。

    kind = "playlist" 代表整份歌單，"video" 代表單一首歌。
    playlist_id 與 video_id 可能同時存在（watch?v=...&list=...），
    此時以歌單為主、單曲為退路（見 pipeline.create_session）。
    """

    kind: str
    id: str
    playlist_id: Optional[str] = None
    video_id: Optional[str] = None


# 這幾種 list 參數不是使用者挑的歌單：RD 是 YouTube 自動接的混音／電台，
# UL 是頻道上傳，LL／WL 是「我的最愛」「稍後觀看」（私人，讀不到）。
# RD 其實讀得到 50 首自動推薦曲，但那是 YouTube 的口味不是使用者的——
# 從播放頁複製連結幾乎都會黏上 &list=RD...，一律只取那一首歌。
_NOT_USER_CURATED_PREFIXES = ("RD", "UL", "LL", "WL")

# /shorts/<id>、/live/<id>、/embed/<id>、/v/<id>
_PATH_VIDEO = re.compile(r"^/(?:shorts|live|embed|v)/([A-Za-z0-9_-]{11})")


def parse_source(url: str) -> Source:
    """解析 YouTube 連結，回傳歌單或單曲。合規要求：僅接受 youtube.com／youtu.be 網域。"""
    raw = (url or "").strip()
    if not raw:
        raise InvalidPlaylistUrl("請貼上 YouTube 歌單或單曲連結。")
    if "://" not in raw:
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise InvalidPlaylistUrl("只接受 http／https 連結。")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise InvalidPlaylistUrl("只接受 youtube.com 或 youtu.be 的連結。")

    query = parse_qs(parsed.query)
    playlist_id = (query.get("list") or [None])[0]
    if playlist_id and not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", playlist_id):
        raise InvalidPlaylistUrl("歌單 ID 格式不正確。")

    video_id = (query.get("v") or [None])[0]
    if not video_id:
        path_match = _PATH_VIDEO.match(parsed.path)
        if path_match:
            video_id = path_match.group(1)
        elif host in ("youtu.be", "www.youtu.be"):
            video_id = parsed.path.lstrip("/").split("/")[0]
    if video_id and not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        video_id = None

    if playlist_id and not (video_id and playlist_id.upper().startswith(_NOT_USER_CURATED_PREFIXES)):
        return Source("playlist", playlist_id, playlist_id, video_id)
    if video_id:
        return Source("video", video_id, playlist_id, video_id)
    raise InvalidPlaylistUrl(
        "這個連結看不出歌單或歌曲，請用「分享 → 複製連結」貼上整份歌單或單一首歌。"
    )


def extract_playlist_id(url: str) -> str:
    """從 YouTube 網址萃取 playlistId；連結只指向單曲時拋 InvalidPlaylistUrl。"""
    source = parse_source(url)
    if source.kind != "playlist":
        raise InvalidPlaylistUrl("這個連結沒有歌單 ID，請用「分享 → 複製連結」貼上整份歌單。")
    return source.id


# --- 曲名正規化 -------------------------------------------------------------

# 括號雜訊：官方 MV／歌詞影片／畫質標記／現場版等
_BRACKET_NOISE = re.compile(
    r"""[\(\[\{【（〔［]\s*
        (?:[^)\]\}】）〕］]*?
           (?:official|lyric|lyrics|mv|m/v|music\s*video|audio|visualizer|video|
              hd|hq|full|4k|1080p|720p|remaster(?:ed)?|explicit|clean|
              live|cover|acoustic|instrumental|karaoke|teaser|trailer|
              動態歌詞|中文歌詞|中字|歌詞|字幕|完整版|官方|高畫質|中文翻譯|純享版)
           [^)\]\}】）〕］]*?)
        \s*[\)\]\}】）〕］]""",
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

# \b 不可省：沒有它，「Soft Lipa」的 ft 會被當成 feat. 標記，歌名只剩「So」
_FEAT = re.compile(r"\s*[\(\[]?\s*\b(?:feat\.?|ft\.?|featuring|with)\s+[^)\]]*[\)\]]?\s*", re.IGNORECASE)
_HASHTAG = re.compile(r"(?:^|\s)#\S+")
_EMOJI = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "←-⇿" "⬀-⯿" "]+"
)
# 撇號不能一律拿掉：「That's What I Like」被清成「That s ...」之後，
# 曲庫與 iTunes 都對不上。只清成對的引號，字中間的撇號留著。
_QUOTES = re.compile(r"""[“”"]|(?<![A-Za-z])['‘’]|['‘’](?![A-Za-z])""")
_STRAY_BRACKETS = re.compile(r"[「」『』《》〈〉【】［］\[\]]")
_MULTISPACE = re.compile(r"\s+")

# 「歌手 - 歌名」的常見分隔符
# 冒號分隔（「Mon Rovîa: Tiny Desk Concert」「宇多田ヒカル：First Love」）放在最後，
# 因為歌名本身含冒號的機率高於前面幾種分隔符。
_SPLITTERS = [" - ", " – ", " — ", " _ ", " / ", "｜", " | ", ": ", "："]

# 「歌手【歌名】」「歌手《歌名》」「歌手「歌名」」「歌手 [ 歌名 ]」——中文／日韓圈
# 常見寫法，括號內是歌名而不是雜訊，必須在切分前優先辨認。
# 方括號要一起收：告五人官方頻道用的是「告五人 Accusefive [ 唯一 Only ]」，
# 少了它整串會被當成歌名，曲庫與 iTunes 都查不到（NOTES #41）。
_TITLE_IN_BRACKET = re.compile(r"^(.{1,40}?)\s*[「《【\[［](.+?)[」》】\]］]\s*$")

# 「歌手 'Song' M/V」——HYBE／SM／YG 這類頻道的固定寫法。引號在 clean_title
# 就會被拿掉，所以這條規則要在拿掉之前先跑。
_TITLE_IN_QUOTES = re.compile(r"^(.{1,60}?)(?:\s|^)[‘'“\"]([^‘'“”’\"]{1,60})[’'”\"]\s*$")

# 括號裡是版本標記而不是歌名時，上面兩條規則都不能套用——
# 「Song [Remix]」的歌名是 Song，不是 Remix。
_VERSION_IN_BRACKET = re.compile(
    r"\b(?:remix|ver\.?|version|edit|mix|remaster(?:ed)?|cover|inst(?:rumental)?|"
    r"acoustic|demo|prod\.?|sped\s*up|slowed|live|karaoke|pt\.?\s*\d|part\s*\d)\b"
    r"|(?:版|翻唱|純音樂)$",
    re.IGNORECASE,
)


def clean_title(raw: str, keep_quotes: bool = False) -> str:
    """去掉 YouTube 曲名裡的行銷雜訊，保留歌手與歌名。

    keep_quotes 只給 split_artist_title 用：「歌手 '歌名'」的引號要留到切分之後。
    """
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
    if not keep_quotes:
        text = _QUOTES.sub(" ", text)
    text = text.strip(" -–—|｜/·、,")
    return _MULTISPACE.sub(" ", text).strip()


def _bracketed_title(text: str) -> Optional[Tuple[str, str]]:
    """「歌手【歌名】」型式，回傳 (歌手, 歌名)；括號裡是版本標記就不算。"""
    match = _TITLE_IN_BRACKET.match(text)
    if not match or not match.group(1).strip():
        return None
    inner = match.group(2).strip()
    if not inner or _VERSION_IN_BRACKET.search(inner):
        return None
    return _tidy_artist(match.group(1)), clean_title(inner)


def _strip_leading_name(title: str, name: str) -> str:
    """歌名開頭重複的歌手／頻道名拿掉：「HYBS Tip Toe」→「Tip Toe」。

    官方頻道很常把歌手名寫進影片標題又不加分隔符，那個前綴會讓曲庫與 iTunes
    一起查不到。整串就是歌手名（例：頻道名當歌名）時不動，否則會清成空字串。
    """
    key = name_key(name)
    text = title.strip()
    if len(key) < 2 or name_key(text) == key:
        return title
    for cut in range(len(text), 1, -1):      # 取最長、正規化後等於歌手名的前綴
        if name_key(text[:cut]) == key:
            rest = text[cut:].strip(" -–—|｜/_·、,:：")
            return rest or title
    return title


def split_artist_title(raw_title: str, channel: Optional[str] = None) -> Tuple[str, str]:
    """回傳 (artist, title)。切不出歌手時退回頻道名（去掉 " - Topic" 等後綴）。"""
    quoted = _TITLE_IN_QUOTES.match(clean_title(raw_title, keep_quotes=True))
    if quoted and quoted.group(1).strip() and not _VERSION_IN_BRACKET.search(quoted.group(2)):
        return _tidy_artist(clean_title(quoted.group(1))), clean_title(quoted.group(2))

    cleaned = clean_title(raw_title)

    bracketed = _bracketed_title(cleaned)
    if bracketed:
        return bracketed

    for splitter in _SPLITTERS:
        if splitter in cleaned:
            left, right = cleaned.split(splitter, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return _tidy_artist(left), clean_title(right)

    fallback_artist = _tidy_artist(
        clean_title(re.sub(r"\s*-\s*Topic$", "", channel or "", flags=re.IGNORECASE))
    )
    title = _MULTISPACE.sub(" ", _STRAY_BRACKETS.sub(" ", cleaned)).strip()
    if fallback_artist:
        title = _strip_leading_name(title, fallback_artist)
    return fallback_artist, title


_PAREN_TAIL = re.compile(r"\s*[\(（\[【][^)）\]】]*[\)）\]】]\s*$")


def _tidy_artist(value: str) -> str:
    """去掉歌手名後面的譯名括號：IU(아이유) → IU。"""
    text = _PAREN_TAIL.sub("", (value or "").strip())
    text = text.strip(" -–—|｜/_·、,:：")
    return text or (value or "").strip()


_LATIN_RUN = re.compile(r"[A-Za-z0-9&\.\'-]+")


def bilingual_parts(text: str) -> Tuple[str, str]:
    """把「中文名 English name」拆成 (拉丁字母部分, 非拉丁部分)，缺的那半回空字串。"""
    value = (text or "").strip()
    latin = " ".join(_LATIN_RUN.findall(value)).strip()
    non_latin = _MULTISPACE.sub(" ", _LATIN_RUN.sub(" ", value)).strip()
    return latin, non_latin


def artist_variants(artist: str) -> list:
    """歌手名可能是「中文名 英文名」並列，回傳可用於外部搜尋的候選寫法（去重、保序）。"""
    text = (artist or "").strip()
    if not text:
        return []
    variants = [text]
    for candidate in bilingual_parts(text):
        if len(candidate) >= 2 and candidate not in variants:
            variants.append(candidate)
    return variants


def title_variants(title: str) -> list:
    """歌名的候選寫法（去重、保序）。

    曲名同樣常見「中文名 English name」並列，而外部曲庫多半只收其中一種：
    YouTube 上是「魚 Fish」，iTunes 上就叫「魚」，整串送出去一筆都查不到。
    歌手名的門檻是 2 個字，歌名這裡放寬到 1——「魚」「浴室」都是真的歌名。
    """
    text = _MULTISPACE.sub(" ", (title or "").strip())
    if not text:
        return []
    variants = [text]
    bare = _PAREN_TAIL.sub("", text).strip()      # 去掉尾巴的 (Live)、(戲劇插曲) 之類
    for candidate in (bare, *bilingual_parts(text)):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants


def name_key(value: str) -> str:
    """名稱正規化：小寫、去標點、壓縮空白。快取 key 與外部搜尋比對共用同一把尺。"""
    value = _MULTISPACE.sub(" ", (value or "").lower().strip())
    return re.sub(r"[^\w一-鿿가-힯぀-ヿ ]+", "", value).strip()


def cache_key(artist: str, title: str) -> str:
    """video_cache 的 _id：正規化後的「歌手|歌名」（§6）。"""
    return "{}|{}".format(name_key(artist), name_key(title))


# 同一位歌手的寫法只差一兩個字時（Official髭男dism ↔ Official鬍子男dism）
# 才算數。門檻放低會把「告五人」配到「五月天」身上，錯配比查不到更糟。
_ARTIST_FUZZY_RATIO = 0.85
_ARTIST_FUZZY_MIN_LEN = 6


def same_artist(wanted: str, found: str) -> bool:
    """歌手比對。中英並列（周杰倫 Jay Chou）任一種寫法對上就算。"""
    found_key = (found or "").strip().lower()
    if not found_key:
        return False
    for variant in artist_variants(wanted):
        key = variant.strip().lower()
        if key and (key in found_key or found_key in key):
            return True

    # 異體字與商店自己的譯名（髭男 ↔ 鬍子男）用包含比不出來，退一步比相似度
    found_norm = name_key(found)
    if len(found_norm) >= _ARTIST_FUZZY_MIN_LEN:
        for variant in artist_variants(wanted):
            key = name_key(variant)
            if len(key) >= _ARTIST_FUZZY_MIN_LEN and \
                    SequenceMatcher(None, key, found_norm).ratio() >= _ARTIST_FUZZY_RATIO:
                return True
    return False


def same_title(wanted: str, found: str) -> bool:
    """曲名比對。允許對方多帶版本標記（(Live)、(LP Version)⋯⋯）。

    短曲名不做「包含」比對——「魚」會誤中「魚仔」，錯配的特徵比沒有特徵更糟。
    """
    a, b = name_key(wanted), name_key(found)
    if not a or not b:
        return False
    if a == b or a == name_key(_PAREN_TAIL.sub("", found)):
        return True
    # 中英並列的寫法只要有一種對上就算：「魚 Fish」＝「魚」＝「Fish」
    wanted_keys = {name_key(v) for v in title_variants(wanted)}
    found_keys = {name_key(v) for v in title_variants(found)}
    if (wanted_keys & found_keys) - {""}:
        return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 6 and shorter in longer
