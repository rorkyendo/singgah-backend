import json
import logging

from openai import OpenAI
from app.core.config import settings, prompts

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.LLM_URL,
)

_EXTRACT_PARAMS_FALLBACK = {
    "id": (
        "Kamu mengekstrak parameter pencarian tempat tinggal dari pesan user. "
        "Kembalikan hanya JSON dengan field: lokasi, budget_min, budget_max, status_pernikahan. "
        "Gunakan data terdaftar jika user tidak menyebutkan nilai baru. "
        "Jangan berikan penjelasan, hanya JSON."
    ),
    "en": (
        "Extract housing search parameters from the user message. "
        "Return only JSON with fields: lokasi, budget_min, budget_max, status_pernikahan. "
        "Use registered data if user does not mention new values. "
        "No explanation, JSON only."
    ),
}


def _normalize_language(language: str) -> str:
    return (language or "id").lower()


def greetingsMessage(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        {"role": "system", "content": prompts.get(lang, "system")},
        {"role": "system", "content": prompts.get(lang, "filter")},
        {"role": "system", "content": prompts.get(lang, "greeting")},
        {"role": "user", "content": userMessage},
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True,
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def consultationMessages(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        {"role": "system", "content": prompts.get(lang, "system")},
        {"role": "system", "content": prompts.get(lang, "filter")},
        {"role": "system", "content": prompts.get(lang, "consultation")},
        {"role": "user", "content": userMessage},
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True,
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def recommendationMessages(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        {"role": "system", "content": prompts.get(lang, "system")},
        {"role": "system", "content": prompts.get(lang, "filter")},
        {"role": "system", "content": prompts.get(lang, "recommendation")},
        {"role": "user", "content": userMessage},
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True,
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def checkRecomendatationResultMessage(details: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        {"role": "system", "content": prompts.get(lang, "system")},
        {"role": "system", "content": prompts.get(lang, "filter")},
        {"role": "system", "content": prompts.get(lang, "check_recommendation")},
        {"role": "user", "content": str(details)},
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True,
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def checkIntenMessage(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        {"role": "system", "content": prompts.get(lang, "check_intent")},
        {"role": "user", "content": userMessage},
    ]

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0,
        max_tokens=5,
        top_p=1,
        stream=False,
    )
    intent = response.choices[0].message.content.strip().lower()

    # Normalize to Indonesian labels used by the controller
    if intent in ("recommendation", "recomendation", "rekomendasi"):
        intent = "rekomendasi"
    elif intent in ("consultation", "consult", "konsultasi"):
        intent = "konsultasi"
    else:
        intent = "lainnya"
    return intent


def extractSearchParams(userMessage: str, user_info: dict, language: str = "id") -> dict:
    """Extract location, budget, and property type from the user message.

    Falls back to registered user_info when the message does not specify them.
    """
    lang = _normalize_language(language)
    system_prompt = prompts.get(lang, "extract_search_params") or _EXTRACT_PARAMS_FALLBACK.get(lang, _EXTRACT_PARAMS_FALLBACK["id"])

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({
            "pesan": userMessage,
            "data_terdaftar": user_info,
        }, ensure_ascii=False)},
    ]

    try:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=0,
            max_tokens=200,
            top_p=1,
            stream=False,
        )
        text = response.choices[0].message.content.strip()
        # Remove markdown code fences if present
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        extracted = json.loads(text)
    except Exception as e:
        logger.warning("extractSearchParams failed: %s", e)
        extracted = {}

    result = dict(user_info)
    for key in ("lokasi", "budget_min", "budget_max", "status_pernikahan"):
        value = extracted.get(key)
        if value is not None and value != "":
            result[key] = value

    # Ensure numeric budgets
    try:
        result["budget_min"] = int(result.get("budget_min", 500000))
    except (TypeError, ValueError):
        result["budget_min"] = 500000
    try:
        result["budget_max"] = int(result.get("budget_max", 3000000))
    except (TypeError, ValueError):
        result["budget_max"] = 3000000

    if result["budget_min"] > result["budget_max"]:
        result["budget_min"], result["budget_max"] = result["budget_max"], result["budget_min"]

    return result
