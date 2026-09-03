"""Intent Parser 與 Explainer（§3.1 凍結簽章）。

介面是「純文字進、JSON 出」，因此三條通道可互換（§1.2）：
  external — 外部 LLM API（選項 A）
  gateway  — 公司內部 LLM Gateway（選項 B，正式落地用）
  stub     — 規則式，不打任何 LLM，內網也能端到端跑通
切換只要改環境變數 LLM_CHANNEL，其他模組完全不動。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

import httpx

from app.config import get_settings
from app.services.http import client
from app.services.prompts import EXPLAIN_SYSTEM, INTENT_SYSTEM, wrap_user_data

log = logging.getLogger("museek.llm")

_proxy_client: Optional["httpx.AsyncClient"] = None


def _llm_client() -> "httpx.AsyncClient":
    """LLM 專用的 HTTP client。

    設了 LLM_PROXY 就走 proxy（Cloud Run 上是容器內 tailscaled 的 userspace proxy，
    讓服務連得到內網的 llm-host）；沒設就沿用共用 client 直連。
    """
    global _proxy_client
    settings = get_settings()
    if not settings.llm_proxy:
        return client()
    if _proxy_client is None or _proxy_client.is_closed:
        _proxy_client = httpx.AsyncClient(proxy=settings.llm_proxy, timeout=settings.llm_timeout)
    return _proxy_client


async def close_llm_client() -> None:
    global _proxy_client
    if _proxy_client is not None and not _proxy_client.is_closed:
        await _proxy_client.aclose()
    _proxy_client = None


# 最近一次 explain 是不是真的由模型產生。降級太安靜會蓋住故障（NOTES #4、#16）。
_last_explain_ok: Optional[bool] = None


def status() -> str:
    settings = get_settings()
    if settings.llm_channel == "stub":
        return "stub"
    if not settings.llm_ready:
        return "unconfigured"
    if _last_explain_ok is False:
        return "degraded"       # 有設定但實際產不出內容，理由已退回模板
    return "configured"


# --- 通道實作 ---------------------------------------------------------------

async def _call_external(system: str, user: str, max_tokens: int = 800) -> str:
    settings = get_settings()
    base = (settings.anthropic_base_url or "https://api.anthropic.com").rstrip("/")
    response = await _llm_client().post(
        f"{base}/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.anthropic_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=20.0,
    )
    response.raise_for_status()
    blocks = response.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


async def _call_gateway(system: str, user: str, max_tokens: int = 1024) -> str:
    """OpenAI 相容端點（地端 vLLM／Azure OpenAI 皆適用）。"""
    settings = get_settings()
    headers = {"content-type": "application/json"}
    if settings.gateway_token:
        headers["authorization"] = f"Bearer {settings.gateway_token}"
    base = str(settings.gateway_base_url).rstrip("/")
    body = {
        "model": settings.gateway_model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if settings.gateway_disable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    response = await _llm_client().post(
        f"{base}/chat/completions",
        headers=headers,
        json=body,
        timeout=settings.llm_timeout,
    )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    # 推理型模型可能把思考過程放在 reasoning 欄位，或直接夾在 content 的 <think> 裡
    return _strip_reasoning(message.get("content") or "")


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    text = _THINK_BLOCK.sub("", text or "")
    # 沒有結束標籤的情況（被 max_tokens 截斷）：整段思考都不要
    if "<think>" in text.lower():
        text = re.split(r"<think>", text, flags=re.IGNORECASE)[0]
    return text.strip()


# 實測發現的參數風格，避免每次都重試一輪
_azure_style: Optional[str] = None


def _azure_body(system: str, user: str, max_tokens: int, style: str) -> Dict:
    body: Dict = {"messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]}
    if style == "modern":
        # gpt-5.x：只吃 max_completion_tokens，且 temperature 只能是預設的 1。
        # 預算必須涵蓋思考 + 輸出，太小會拿到空的 content（見 config 註解）。
        body["max_completion_tokens"] = max(max_tokens, get_settings().azure_min_completion_tokens)
    else:
        body["max_tokens"] = max_tokens
        body["temperature"] = 0.2
    return body


async def _call_azure(system: str, user: str, max_tokens: int = 800) -> str:
    """Azure OpenAI。與 gateway 通道的差異見 config.py 的註解。

    不同世代的 Azure 模型參數不相容：gpt-5.x 用 max_completion_tokens 且拒絕
    自訂 temperature，gpt-4o 則相反。auto 模式第一次呼叫時偵測並記住。
    """
    global _azure_style
    settings = get_settings()
    endpoint = str(settings.azure_endpoint).rstrip("/")
    url = (f"{endpoint}/openai/deployments/{settings.azure_deployment}"
           f"/chat/completions?api-version={settings.azure_api_version}")
    headers = {"api-key": settings.azure_api_key or "", "content-type": "application/json"}

    configured = settings.azure_param_style
    styles = [configured] if configured != "auto" else [_azure_style or "modern"]
    if configured == "auto" and _azure_style is None:
        styles.append("legacy")      # modern 被拒就換 legacy 再試一次

    last_error = None
    for style in styles:
        response = await _llm_client().post(
            url, headers=headers,
            json=_azure_body(system, user, max_tokens, style),
            timeout=settings.llm_timeout,
        )
        if response.status_code == 400:
            detail = response.json().get("error", {})
            if detail.get("code") in ("unsupported_parameter", "unsupported_value"):
                log.info("Azure 不接受 %s 風格參數（%s），改試另一種",
                         style, detail.get("param"))
                last_error = detail.get("message")
                continue
        response.raise_for_status()
        _azure_style = style
        message = response.json()["choices"][0]["message"]
        return _strip_reasoning(message.get("content") or "")

    raise RuntimeError(f"Azure 參數不相容：{last_error}")


async def _complete(system: str, user: str, max_tokens: int = 800) -> str:
    settings = get_settings()
    if settings.llm_channel == "external" and settings.anthropic_api_key:
        return await _call_external(system, user, max_tokens)
    if settings.llm_channel == "gateway" and settings.gateway_base_url:
        return await _call_gateway(system, user, max_tokens)
    if settings.llm_channel == "azure" and settings.llm_ready:
        return await _call_azure(system, user, max_tokens)
    raise RuntimeError("LLM 通道未設定")


def _extract_json(text: str) -> Dict:
    """從模型回應中取出第一個完整的 JSON 物件。

    貪婪的 `{.*}` 會把前後的敘述或思考內容一起吞進來，因此改成掃描平衡括號。
    """
    cleaned = _strip_reasoning(text)
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start:index + 1])
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)
    raise ValueError("回應中找不到合法 JSON")


# --- §3.1 對外簽章 -----------------------------------------------------------

async def parse_intent(user_text: str) -> Dict:
    """回傳 Intent JSON（§3.3）。LLM 不可用或回傳非合法 JSON 就退回規則式解析。"""
    settings = get_settings()
    if settings.llm_channel != "stub" and settings.llm_ready:
        prompt = wrap_user_data(user_text)
        for attempt in range(2):  # §9：非合法 JSON 重試 1 次
            try:
                system = INTENT_SYSTEM if attempt == 0 else INTENT_SYSTEM + "\n\n只輸出 JSON。"
                raw = await _complete(system, prompt, max_tokens=800)
                return _normalize_intent(_extract_json(raw))
            except Exception as error:  # noqa: BLE001
                log.warning("parse_intent 第 %d 次失敗：%s", attempt + 1, error)
    return rule_based_intent(user_text)


async def explain(user_vector: Dict, candidate: Dict, context: str) -> str:
    """回傳 60 字內繁體中文理由。失敗就退回模板——理由裡的數字一律取自音訊特徵。"""
    settings = get_settings()
    if settings.llm_channel != "stub" and settings.llm_ready:
        features = candidate.get("features") or {}
        payload = (
            f"使用者品味向量：{json.dumps(_round(user_vector), ensure_ascii=False)}\n"
            f"候選曲目音訊特徵：{json.dumps(_round(features), ensure_ascii=False)}\n"
            f"使用者情境：{wrap_user_data(context)}\n"
            f"曲目資訊：{wrap_user_data(candidate.get('artist', '') + ' - ' + candidate.get('title', ''))}"
        )
        try:
            text = (await _complete(EXPLAIN_SYSTEM, payload, max_tokens=300)).strip()
            if text:
                _mark_explain(True)
                return _trim_reason(text)
            log.warning("explain 回傳空內容（多半是思考佔滿 max_tokens），改用模板")
        except Exception as error:  # noqa: BLE001
            log.warning("explain 失敗，改用模板：%s", error)
        _mark_explain(False)
    return template_reason(user_vector, candidate)


def _mark_explain(ok: bool) -> None:
    global _last_explain_ok
    _last_explain_ok = ok


_SENTENCE_END = "。！？!?"


def _trim_reason(text: str, limit: int = 110) -> str:
    """模型常寫超過 60 字。硬切會在句中斷掉，因此退到最後一個句尾標點。"""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(char) for char in _SENTENCE_END)
    return window[:cut + 1] if cut > 20 else window.rstrip("，、；:：") + "…"


def _round(vector: Dict) -> Dict:
    return {k: (round(v, 3) if isinstance(v, (int, float)) else v) for k, v in (vector or {}).items()}


def _normalize_intent(raw: Dict) -> Dict:
    """把 LLM 回傳整成契約形狀，順便擋掉超出範圍的數值。"""
    constraints = raw.get("constraints") or {}
    cleaned: Dict[str, Optional[object]] = {}
    for key in ("energy_max", "energy_min", "valence_max", "valence_min",
                "acousticness_min", "acousticness_max"):
        value = constraints.get(key)
        if isinstance(value, (int, float)):
            cleaned[key] = min(1.0, max(0.0, float(value)))
    tempo = constraints.get("tempo_range")
    if isinstance(tempo, list) and len(tempo) == 2 and all(isinstance(t, (int, float)) for t in tempo):
        cleaned["tempo_range"] = [float(min(tempo)), float(max(tempo))]

    def as_list(value) -> List[str]:
        return [str(v) for v in value][:5] if isinstance(value, list) else []

    return {
        "mood": raw.get("mood") if raw.get("mood") in MOODS else None,
        "activity": raw.get("activity") if raw.get("activity") in ACTIVITIES else None,
        "constraints": cleaned,
        "reference_artists": as_list(raw.get("reference_artists")),
        "avoid": as_list(raw.get("avoid")),
        "exploration": raw.get("exploration") if raw.get("exploration") in ("high", "medium", "low") else "medium",
    }


# --- 規則式解析（stub 通道／LLM 降級路徑）------------------------------------

MOODS = ("低落", "平靜", "愉悅", "激昂")
ACTIVITIES = ("開車", "通勤", "工作", "運動", "放空", "入睡")

_MOOD_RULES = [
    ("低落", ["低落", "難過", "傷心", "憂鬱", "emo", "沮喪", "失戀", "想哭"]),
    ("激昂", ["激昂", "嗨", "熱血", "亢奮", "衝", "爆發", "興奮", "運動", "健身"]),
    ("愉悅", ["愉悅", "開心", "快樂", "好心情", "輕快", "陽光"]),
    ("平靜", ["平靜", "放鬆", "冷靜", "舒服", "安靜", "放空", "療癒", "chill"]),
]
_ACTIVITY_RULES = [
    ("開車", ["開車", "駕駛", "上路", "兜風", "公路"]),
    ("入睡", ["入睡", "睡覺", "助眠", "睡前", "失眠"]),
    ("運動", ["運動", "健身", "跑步", "重訓", "有氧"]),
    ("通勤", ["通勤", "捷運", "公車", "上班路上", "上學路上"]),
    ("工作", ["工作", "唸書", "讀書", "專注", "寫程式", "加班", "辦公"]),
    ("放空", ["放空", "發呆", "耍廢", "散步"]),
]


def rule_based_intent(user_text: str) -> Dict:
    """不打任何 LLM 的情境解析。內網開發、LLM 掛掉、Demo 備援都靠這條。"""
    text = (user_text or "").lower()
    constraints: Dict[str, object] = {}
    avoid: List[str] = []

    def has(*words: str) -> bool:
        return any(word.lower() in text for word in words)

    mood = next((name for name, keys in _MOOD_RULES if has(*keys)), None)
    activity = next((name for name, keys in _ACTIVITY_RULES if has(*keys)), None)

    if has("不要太吵", "太吵", "安靜", "小聲", "輕柔", "不要吵", "低調"):
        constraints["energy_max"] = 0.5
        avoid.append("強烈鼓組")
    if has("放空", "放鬆", "chill", "冷靜", "療癒"):
        constraints.setdefault("energy_max", 0.6)
    if activity == "入睡":
        constraints["energy_max"] = min(float(constraints.get("energy_max", 1.0)), 0.35)
        constraints["tempo_range"] = [50.0, 85.0]
        constraints.setdefault("acousticness_min", 0.4)
    if activity in ("運動", "健身") or has("嗨", "熱血", "衝一波"):
        constraints["energy_min"] = 0.6
        constraints["tempo_range"] = [110.0, 165.0]
        constraints.pop("energy_max", None)
    if activity == "工作" and "tempo_range" not in constraints:
        constraints.setdefault("energy_max", 0.55)
        avoid.append("人聲干擾")
    if has("原音", "木吉他", "acoustic", "不插電"):
        constraints["acousticness_min"] = 0.5
    if has("有電子", "電子感", "合成器", "synth"):
        constraints["acousticness_max"] = 0.4
    if mood == "低落" and has("不要", "別"):
        avoid.append("過度悲傷")
    if mood == "愉悅":
        constraints.setdefault("valence_min", 0.5)
    if mood == "低落" and not has("開心", "振作"):
        constraints.setdefault("valence_max", 0.6)
    if activity == "開車" and "tempo_range" not in constraints:
        constraints.setdefault("tempo_range", [70.0, 110.0])

    if has("驚喜", "沒聽過", "冷門", "新的", "沒聽過的", "小眾"):
        exploration = "high"
    elif has("類似", "熟悉", "一樣", "差不多", "平常聽"):
        exploration = "low"
    else:
        exploration = "medium"

    return {
        "mood": mood,
        "activity": activity,
        "constraints": constraints,
        "reference_artists": [],
        "avoid": avoid,
        "exploration": exploration,
    }


_LABELS = {
    "energy": "能量", "valence": "情緒明亮度", "danceability": "律動感",
    "acousticness": "原音比例", "instrumentalness": "純器樂程度", "tempo": "速度",
}


def template_reason(user_vector: Dict, candidate: Dict) -> str:
    """模板理由：引用的每個數字都來自音訊特徵，不是 LLM 猜的。"""
    features = candidate.get("features") or {}
    shared = [k for k in ("energy", "valence", "danceability", "acousticness", "tempo")
              if k in features and k in user_vector]
    if not shared:
        return "音訊特徵與你的歌單接近，適合現在的情境。"

    def gap(key: str) -> float:
        scale = 200.0 if key == "tempo" else 1.0
        return abs(float(features[key]) - float(user_vector[key])) / scale

    closest = min(shared, key=gap)
    farthest = max(shared, key=gap)
    unit = " BPM" if closest == "tempo" else ""
    unit_far = " BPM" if farthest == "tempo" else ""
    close_text = f"{_LABELS[closest]} {float(features[closest]):.2f}{unit}".replace(".00 BPM", " BPM")

    if farthest == closest:
        return f"{close_text} 與你常聽的幾乎一致，屬於熟悉範圍內的選擇。"
    direction = "高" if float(features[farthest]) > float(user_vector[farthest]) else "低"
    far_text = f"{_LABELS[farthest]} {float(features[farthest]):.2f}{unit_far}".replace(".00 BPM", " BPM")
    return f"{close_text}，與你平常聽的幾乎一致；但{far_text}，比你的平均{direction}出一截。"
