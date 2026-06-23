from openai import OpenAI
from app.core.config import settings

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
