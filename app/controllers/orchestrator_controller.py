from openai import OpenAI
from app.core.config import settings

client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.LLM_URL,
)

def greetingsMessage(userMessage: str):
    messages = [
        { "role": "system", "content": settings.SYSTEM_PROMPT },
        { "role": "system", "content": settings.FILTER_PROMPT },
        { "role": "system", "content": settings.GREETING_PROMPT },
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

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream)
    return response_text

def consultationMessages(userMessage: str):
    messages = [
        { "role": "system", "content": settings.SYSTEM_PROMPT },
        { "role": "system", "content": settings.FILTER_PROMPT },
        { "role": "system", "content": settings.CONDITIONAL_PROMPT },
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

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream)
    return response_text

def recommendationMessages(userMessage: str):
    messages = [
        { "role": "system", "content": settings.SYSTEM_PROMPT },
        { "role": "system", "content": settings.FILTER_PROMPT },
        { "role": "system", "content": settings.RECOMMENDATION_PROMPT },
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

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream)
    return response_text

def checkRecomendatationResultMessage(details: str):
    messages = [
        { "role": "system", "content": settings.SYSTEM_PROMPT },
        { "role": "system", "content": settings.FILTER_PROMPT },
        { "role": "system", "content": settings.CHECK_RECOMENDATION_PROMPT },
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

    response_text = "".join(chunk.choices[0].delta.content for chunk in stream)
    return response_text

def checkIntenMessage(userMessage: str):
    messages = [
        { "role": "system", "content": settings.CHECK_INTENT_PROMPT },
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
    return intent
