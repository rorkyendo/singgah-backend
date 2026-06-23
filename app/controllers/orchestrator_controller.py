import json
import logging

from openai import OpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.LLM_URL,
)


def _get_prompt(language: str, prompt_id: str) -> str:
    lang = language.lower() if language else "id"
    if lang == "en":
        return getattr(settings, f"{prompt_id}_EN", getattr(settings, prompt_id, ""))
    return getattr(settings, prompt_id, "")


def _normalize_language(language: str) -> str:
    return (language or "id").lower()


def greetingsMessage(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        { "role": "system", "content": _get_prompt(lang, "SYSTEM_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "FILTER_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "GREETING_PROMPT") },
        { "role": "user", "content": userMessage }
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def consultationMessages(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        { "role": "system", "content": _get_prompt(lang, "SYSTEM_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "FILTER_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "CONDITIONAL_PROMPT") },
        { "role": "user", "content": userMessage }
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def recommendationMessages(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        { "role": "system", "content": _get_prompt(lang, "SYSTEM_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "FILTER_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "RECOMMENDATION_PROMPT") },
        { "role": "user", "content": userMessage }
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def checkRecomendatationResultMessage(details: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        { "role": "system", "content": _get_prompt(lang, "SYSTEM_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "FILTER_PROMPT") },
        { "role": "system", "content": _get_prompt(lang, "CHECK_RECOMENDATION_PROMPT") },
        { "role": "user", "content": str(details) },
    ]

    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0.5,
        max_tokens=500,
        top_p=0.7,
        stream=True
    )

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream if chunk.choices[0].delta.content)
    return response_text

def checkIntenMessage(userMessage: str, language: str = "id"):
    lang = _normalize_language(language)
    messages = [
        { "role": "system", "content": _get_prompt(lang, "CHECK_INTENT_PROMPT") },
        { "role": "user", "content": userMessage }
    ]

    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        temperature=0,
        max_tokens=5,
        top_p=1,
        stream=False
    )
    intent = response.choices[0].message.content.strip().lower()

    # normalize English output to Indonesian labels used by the controller
    if lang == "en":
        if intent in ("recommendation", "recomendation"):
            intent = "rekomendasi"
        elif intent in ("consultation", "consult"):
            intent = "konsultasi"
        else:
            intent = "lainnya"
    return intent


def extractSearchParams(userMessage: str, user_info: dict, language: str = "id") -> dict:
    """Extract location, budget, and property type from the user message.

    Falls back to registered user_info when the message does not specify them.
    """
    lang = _normalize_language(language)
    prompt_id = "EXTRACT_SEARCH_PARAMS_PROMPT"
    system_prompt = _get_prompt(lang, prompt_id) or (
        "Kamu mengekstrak parameter pencarian tempat tinggal dari pesan user. "
        "Kembalikan hanya JSON dengan field: lokasi, budget_min, budget_max, status_pernikahan. "
        "Gunakan data terdaftar jika user tidak menyebutkan nilai baru. "
        "Jangan berikan penjelasan, hanya JSON."
    )

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
