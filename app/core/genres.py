"""曲風這一軸。純函式，不呼叫任何 API（對照 core/regions.py）。

**為什麼不把曲風塞進那支六維向量。** §5.1 的六個維度是連續且可比的，
歐氏距離對它們有意義；曲風是類別，硬編碼進同一個距離要憑空發明一個尺度
（citypop 到 R&B 的「距離」是 0.3 還是 0.7？沒有答案）。而且真正的症狀正好
說明了問題：使用者抱怨「數值差不多但曲風不一樣」——那表示距離函式算對了，
是**少了一個軸**，不是那個軸算錯了。所以曲風獨立成一項分數、獨立配名額，
跟地區比重的做法一致。

## 三件事

1. `normalize()`：把外部來的自由字串（iTunes 的 `R&B/Soul` 與 `華語流行樂`、
   使用者打的「城市流行」）收斂成標準 slug。
2. `affinity()`：兩個 slug 有多像。**不是 0/1**——R&B 跟 neo soul 幾乎是同一件事，
   citypop 跟 funk 沾得上邊，跟 metal 就是沒關係。全 0/1 的話「想聽 R&B」
   會把 neo soul 一起排掉，那比不做還糟。
3. `genre_fit()`：候選對上使用者想要的曲風有多合，**查不到標籤時回 None**——
   「不知道」不等於「不合」。這跟 regions.region_of 回空字串是同一個紀律，
   而且這裡更要緊：沒有標籤的候選佔多數，把 None 當 0 會讓排序退化成
   「比誰有標籤」。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Set

# --- 標準曲風與別名 ---------------------------------------------------------
#
# 別名採**整詞比對**，不是子字串：`trap` 裡面有 `rap`，子字串比對會把每一首
# trap 都標成 hip hop 的同時也標成 rap，錯得很安靜。
#
# 別名要涵蓋三種來源，缺一種就會有一整類標籤被安靜地丟掉：
#   1. iTunes **US 商店**的英文寫法（`R&B/Soul`、`Hip-Hop/Rap`、`Adult Contemporary`）
#   2. iTunes **TW 商店**的中文寫法——**同一個概念的另一種寫法，不是另一個概念**
#      （`華語流行樂`＝Mandopop、`嘻哈/饒舌`＝Hip-Hop/Rap、`另類音樂`＝Alternative）
#   3. 使用者自己會打的中英文（「想聽 citypop」「來點爵士」）
# 第 1、2 項是實測 46 位歌手、收集到的 40 種實際回傳字串，不是照文件猜的。
ALIASES: Dict[str, List[str]] = {
    # iTunes 沒有這個分類（山下達郎回 J-Pop、落日飛車回「成人當代」），所以
    # 這個 slug 目前只有使用者打得出來。留著是因為 affinity 仍然有用：
    # 「想聽 citypop」會經由 RELATED 對上 adult_contemporary／funk／jpop。
    "city_pop": ["city pop", "citypop", "城市流行", "都會流行"],
    # iTunes 把落日飛車、Men I Trust 這一圈放這裡——它是目前離 citypop 最近的格子
    "adult_contemporary": ["adult contemporary", "成人當代"],
    "rnb": ["rnb", "r n b", "rhythm and blues", "contemporary rnb", "alternative rnb",
            "當代 rnb", "當代rnb", "節奏藍調", "rb"],
    "neo_soul": ["neo soul", "neosoul", "新靈魂樂"],
    "soul": ["soul", "motown", "靈魂樂", "rnb 靈魂樂"],
    "funk": ["funk", "funky", "放克"],
    "disco": ["disco", "boogie", "迪斯可"],
    "jazz": ["jazz", "swing", "bebop", "爵士"],
    "bossa_nova": ["bossa nova", "bossanova", "samba", "巴薩諾瓦"],
    "hip_hop": ["hip hop", "hiphop", "rap", "boom bap", "嘻哈", "饒舌", "說唱",
                "嘻哈 饒舌", "華語嘻哈"],
    "trap": ["trap", "drill"],
    "lofi": ["lofi", "lo fi", "chillhop", "jazzy hip hop"],
    "pop": ["pop", "art pop", "流行", "流行樂"],
    "synthpop": ["synthpop", "synth pop", "new wave", "電子流行"],
    "dream_pop": ["dream pop", "dreampop", "bedroom pop"],
    "shoegaze": ["shoegaze", "shoegazing", "自賞"],
    # iTunes 的 `Alternative`／`另類音樂` 是它最常用的一格（實測 46 位裡出現 79 次），
    # 涵蓋範圍就是獨立／另類那一圈，收在這裡而不是自成一格
    "indie_rock": ["indie rock", "indie", "indie pop", "獨立搖滾", "獨立",
                   "alternative", "另類音樂", "另類"],
    "math_rock": ["math rock", "midwest emo", "數學搖滾"],
    "post_rock": ["post rock", "postrock", "後搖", "後搖滾"],
    "rock": ["rock", "classic rock", "hard rock", "搖滾", "korean rock"],
    "punk": ["punk", "hardcore", "龐克"],
    "emo": ["emo", "screamo"],
    "metal": ["metal", "metalcore", "重金屬", "金屬"],
    "folk": ["folk", "americana", "bluegrass", "民謠", "另類民謠"],
    "singer_songwriter": ["singer songwriter", "songwriter", "創作歌手"],
    "country": ["country", "鄉村"],
    "ambient": ["ambient", "drone", "environmental", "氛圍"],
    "classical": ["classical", "neoclassical", "piano", "orchestra", "古典",
                  "古典音樂", "古典跨界", "classical crossover"],
    "edm": ["edm", "electronic", "electronica", "電音", "電子", "電子音樂",
            "dance", "舞曲"],
    "house": ["house", "deep house", "tech house"],
    "techno": ["techno", "trance"],
    "drum_and_bass": ["drum and bass", "dnb", "drum n bass", "jungle", "breakbeat"],
    "mandopop": ["mandopop", "c pop", "cpop", "taiwan pop", "chinese pop", "華語流行",
                 "華語", "國語流行", "華語流行樂"],
    "jpop": ["jpop", "j pop", "japanese pop", "japan pop", "anime", "日系", "日本流行",
             "日本流行樂"],
    "kpop": ["kpop", "k pop", "korean pop", "韓流", "韓國流行", "韓國流行樂"],
    "citywide_asia_indie": ["taiwan indie", "chinese indie", "japanese indie",
                            "korean indie", "thai indie", "indonesian indie"],
    "reggae": ["reggae", "dub", "ska"],
    "afrobeats": ["afrobeats", "afrobeat", "amapiano"],
    "latin": ["latin", "reggaeton", "salsa", "拉丁"],
    "blues": ["blues"],
    "gospel": ["gospel", "worship"],
    "soundtrack": ["soundtrack", "score", "film music", "配樂", "原聲帶"],
}

# 上位曲風。標到子類就順便補上父類——使用者說「搖滾」時 shoegaze 要對得上，
# 而 iTunes 只會回一個 `Shoegaze`，字串裡不會出現 rock 這個詞。
PARENTS: Dict[str, str] = {
    "city_pop": "pop", "mandopop": "pop", "jpop": "pop", "kpop": "pop",
    "synthpop": "pop", "dream_pop": "indie_rock", "shoegaze": "indie_rock",
    "math_rock": "indie_rock", "indie_rock": "rock", "post_rock": "rock",
    "punk": "rock", "emo": "punk", "metal": "rock",
    "neo_soul": "soul", "trap": "hip_hop", "lofi": "hip_hop",
    "house": "edm", "techno": "edm", "drum_and_bass": "edm",
    "bossa_nova": "jazz", "singer_songwriter": "folk",
    "citywide_asia_indie": "indie_rock",
}

# 父子關係本身給的相似度。「想聽 citypop」拿到一首泛泛的 pop 是**弱命中**，
# 不是命中——所以這個數字要明顯小於 1，但不能是 0。
PARENT_AFFINITY = 0.4

# 跨家族的相似度。只寫真的沾得上邊的，寧可漏也不要亂連——
# 這張表寫寬一點，「想聽 R&B」就會開始回搖滾，那是這個功能最糟的失敗方式。
_RELATED_RAW = [
    ("rnb", "neo_soul", 0.85), ("rnb", "soul", 0.70), ("rnb", "hip_hop", 0.45),
    ("rnb", "kpop", 0.35), ("neo_soul", "jazz", 0.45), ("soul", "funk", 0.65),
    ("city_pop", "funk", 0.55), ("city_pop", "disco", 0.50), ("city_pop", "jpop", 0.50),
    ("city_pop", "jazz", 0.35), ("city_pop", "synthpop", 0.45),
    # iTunes 給不出 citypop，落日飛車那一圈會落在 adult_contemporary。這條邊
    # 是「想聽 citypop」目前唯一能命中的路，所以給得比其他鄰居高一點
    ("city_pop", "adult_contemporary", 0.60),
    ("adult_contemporary", "pop", 0.50), ("adult_contemporary", "soul", 0.35),
    ("disco", "funk", 0.70), ("disco", "house", 0.50),
    ("lofi", "jazz", 0.45), ("lofi", "ambient", 0.40),
    ("dream_pop", "shoegaze", 0.75), ("dream_pop", "ambient", 0.35),
    ("post_rock", "ambient", 0.40), ("math_rock", "post_rock", 0.45),
    ("edm", "synthpop", 0.45), ("house", "techno", 0.70),
    ("folk", "country", 0.55), ("folk", "ambient", 0.25),
    ("classical", "ambient", 0.40), ("classical", "soundtrack", 0.55),
    ("jazz", "blues", 0.55), ("blues", "rock", 0.40), ("soul", "gospel", 0.55),
    ("hip_hop", "afrobeats", 0.35), ("latin", "bossa_nova", 0.40),
]

RELATED: Dict[str, Dict[str, float]] = {}
for _a, _b, _w in _RELATED_RAW:
    RELATED.setdefault(_a, {})[_b] = _w
    RELATED.setdefault(_b, {})[_a] = _w

# 顯示用的人話標籤（前端的曲風標籤、LLM 理由用得到）
LABELS: Dict[str, str] = {
    "city_pop": "City Pop", "adult_contemporary": "成人當代", "rnb": "R&B", "neo_soul": "Neo Soul", "soul": "Soul",
    "funk": "Funk", "disco": "Disco", "jazz": "Jazz", "bossa_nova": "Bossa Nova",
    "hip_hop": "Hip-Hop", "trap": "Trap", "lofi": "Lo-fi", "pop": "Pop",
    "synthpop": "Synth Pop", "dream_pop": "Dream Pop", "shoegaze": "Shoegaze",
    "indie_rock": "Indie Rock", "math_rock": "Math Rock", "post_rock": "Post Rock",
    "rock": "Rock", "punk": "Punk", "emo": "Emo", "metal": "Metal", "folk": "Folk",
    "singer_songwriter": "創作歌手", "country": "Country", "ambient": "Ambient",
    "classical": "古典", "edm": "電子", "house": "House", "techno": "Techno",
    "drum_and_bass": "Drum & Bass", "mandopop": "華語流行", "jpop": "J-Pop",
    "kpop": "K-Pop", "citywide_asia_indie": "亞洲獨立", "reggae": "Reggae",
    "afrobeats": "Afrobeats", "latin": "Latin", "blues": "Blues", "gospel": "Gospel",
    "soundtrack": "配樂",
}

GENRES = tuple(ALIASES)


def label(slug: str) -> str:
    return LABELS.get(slug, slug.replace("_", " "))


# --- 正規化 ------------------------------------------------------------------

def _flatten(text: str) -> str:
    """把自由字串壓成「空白分隔的整詞」形式，好做整詞比對。

    `R&B/Soul` → ` rnb soul `、`Hip-Hop/Rap` → ` hip hop rap `。
    & 直接換成 n 是為了讓 `R&B` 與使用者打的 `RnB` 走到同一個別名上。
    """
    lowered = str(text or "").lower().replace("&", "n")
    return " " + re.sub(r"[^0-9a-z一-鿿]+", " ", lowered).strip() + " "


# 中文別名沒有空白可以當邊界，要另外用子字串比對（「華語流行」不會被空白切開）
def _is_cjk(text: str) -> bool:
    return any("一" <= char <= "鿿" for char in text)


_ALIAS_INDEX = [(slug, alias, _is_cjk(alias))
                for slug, names in ALIASES.items() for alias in names]


def _with_parents(slugs: Set[str]) -> Set[str]:
    """補上整條上位鏈：shoegaze → indie_rock → rock，三個都標。

    一路補到頂而不是只補一層，因為那條鏈上的每一層都是**事實**——
    一首 shoegaze 就是 indie rock、也就是 rock。只補一層的話，
    「想聽搖滾」對上一首 shoegaze 只拿得到隔代的 0.4 分，
    但那首歌明明就是搖滾。

    PARENTS 是人工維護的，寫錯就會繞圈；用 seen 擋住，繞到自己就停。
    """
    out = set(slugs)
    for slug in slugs:
        current, seen = slug, {slug}
        while current in PARENTS:
            current = PARENTS[current]
            if current in seen:
                break
            seen.add(current)
            out.add(current)
    return out


def normalize(raw: Iterable[str], *, parents: bool = True) -> Set[str]:
    """把外部標籤整成標準 slug 集合。認不出來的一律丟掉，不硬湊。

    輸入可以是 iTunes 的 primaryGenreName（中英兩種寫法都收），
    或使用者／LLM 給的詞。同一個 slug 只會出現一次。

    **parents 只有標候選時該開。** 補父類是為了讓「想聽搖滾」對得上一首
    只標了 shoegaze 的歌；但反過來把它用在「使用者想要什麼」那一側就慘了——
    「想聽 citypop」會被展開成 {city_pop, pop}，而 genre_fit 取的是 max，
    於是**任何一首泛泛的流行歌都變成滿分**，等於這個功能沒開。
    同理 avoid：「不要 trap」不該連整個嘻哈一起封掉。
    """
    found: Set[str] = set()
    for item in raw or []:
        text = str(item or "").strip()
        if not text:
            continue
        if text in ALIASES:          # 已經是 slug 就直接收（LLM 回傳的就是這種）
            found.add(text)
            continue
        flat = _flatten(text)
        for slug, alias, cjk in _ALIAS_INDEX:
            if (alias in text) if cjk else (f" {alias} " in flat):
                found.add(slug)
    return _with_parents(found) if parents else found


def coerce(values: Iterable[str], limit: int = 5) -> List[str]:
    """給契約用的版本：正規化後回成排序清單（集合不能進 JSON）。

    這支專門用在「使用者想要／不要什麼」那一側，所以**不補父類**（見 normalize）。
    """
    return sorted(normalize(values, parents=False))[:limit]


# --- 相似度 ------------------------------------------------------------------

def affinity(wanted: str, found: str) -> float:
    """兩個 slug 有多像，落在 [0, 1]。完全相同是 1，毫無關係是 0。"""
    if not wanted or not found:
        return 0.0
    if wanted == found:
        return 1.0
    # RELATED 先查、PARENTS 後查：手寫的那張表是**針對這一對**寫的，
    # 父子關係給的 PARENT_AFFINITY 只是通則。反過來的話，只要哪天在 RELATED
    # 裡替一對父子寫了數字，那個數字會被通則無聲蓋掉——查很久才會發現。
    found_affinity = RELATED.get(wanted, {}).get(found)
    if found_affinity is not None:
        return found_affinity
    if PARENTS.get(wanted) == found or PARENTS.get(found) == wanted:
        return PARENT_AFFINITY
    return 0.0


def genre_fit(wanted: Mapping[str, float], candidate: Iterable[str]) -> Optional[float]:
    """候選的曲風有多合，落在 [0, 1]；**無從判斷時回 None**。

    wanted 是「想要的曲風 → 權重」。使用者明講的曲風權重都是 1；
    從歌單統計出來的分布則帶著各自的比重，主要曲風權重最高。

    取 **max 而不是平均**：使用者說「想聽 citypop 或 R&B」時，一首漂亮的
    citypop 就該滿分，不該因為它不是 R&B 而被打對折。權重先除以最大值，
    所以「命中我最常聽的那個曲風」＝1.0，命中邊緣曲風則按比例遞減。

    回 None 的兩種情況意義不同，但處置一樣（見 ranker：整項連同權重拿掉）：
      * wanted 是空的 —— 使用者沒指定，也沒有歌單可統計，這一軸無從談起；
      * candidate 是空的 —— 那首歌查不到標籤，這是資料缺口不是它的錯。
    """
    tags = {slug for slug in candidate if slug}
    weights = {slug: float(w) for slug, w in (wanted or {}).items() if w and w > 0}
    if not tags or not weights:
        return None
    top = max(weights.values())
    return max((weight / top) * affinity(slug, tag)
               for slug, weight in weights.items() for tag in tags)


def blocked(avoid: Iterable[str], candidate: Iterable[str]) -> bool:
    """候選是不是使用者明講不要的曲風。

    只認**完全命中**，不牽連相關曲風：使用者說「不要嘻哈」時把 lo-fi 一起
    排掉是過度解讀，而硬過濾一旦過度解讀，候選池會安靜地少掉一大塊。
    """
    unwanted = normalize(avoid, parents=False)
    return bool(unwanted & {slug for slug in candidate if slug})


# --- 候選身上的曲風 ----------------------------------------------------------

def genres_of(candidate: Dict) -> Set[str]:
    """候選帶著的曲風標籤。沒有就是空集合——空集合代表「沒有證據」，不是「不合」。"""
    return {str(slug) for slug in (candidate.get("genres") or []) if slug}


def leaves(slugs: Iterable[str]) -> Set[str]:
    """只留最具體的那一層：被同一列其他標籤蘊含的上位曲風不算。

    `{shoegaze, indie_rock, rock}` → `{shoegaze}`；`{rnb, soul}` 兩個都留
    （彼此沒有上下位關係，iTunes 的 `R&B/Soul` 本來就是兩件事都講了）。
    """
    slugs = {slug for slug in slugs if slug}
    inherited: Set[str] = set()
    for slug in slugs:
        current, seen = slug, {slug}
        while current in PARENTS:
            current = PARENTS[current]
            if current in seen:
                break
            seen.add(current)
            inherited.add(current)
    return (slugs - inherited) or slugs


def distribution(rows: Iterable[Dict], limit: int = 6) -> Dict[str, float]:
    """把一疊曲目的曲風統計成分布，權重正規化到最大值為 1。

    這是「使用者沒明講曲風時」的預設 wanted。歌單入口靠它——
    平均向量表達不了「這個人聽的是 citypop 不是 soft rock」，這份分布可以。

    **只統計最具體的那一層。** 候選身上的上位曲風是我們自己補的（`indie_rock`
    一定帶著 `rock`），它是推論不是觀察；照單全收的話，一份清一色獨立搖滾的
    歌單會統計出 `{indie_rock: 1.0, rock: 1.0}`，而 metal 的上位也是 rock
    ——**一首 metal 就拿到滿分命中**。實測過，那正是「數值對但曲風不對」
    最後殘留的那一塊。

    注意這只影響「使用者的品味長什麼樣」；候選那一側仍然保有整條上位鏈，
    所以「想聽搖滾」照樣對得上一首 shoegaze。兩側的需求是相反的：
    描述一個人要盡量具體，比對一首歌要盡量寬。
    """
    counts: Dict[str, float] = {}
    for row in rows:
        for slug in leaves(genres_of(row)):
            counts[slug] = counts.get(slug, 0.0) + 1.0
    if not counts:
        return {}
    top = max(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return {slug: round(count / top, 4) for slug, count in ranked}
