from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    PROJECT_NAME: str
    API_KEY: str
    LLM_MODEL: str
    LLM_URL: str
    SYSTEM_PROMPT: str
    GREETING_PROMPT: str
    FILTER_PROMPT: str
    CHECK_INTENT_PROMPT: str
    CONDITIONAL_PROMPT: str
    RECOMMENDATION_PROMPT: str
    CHECK_RECOMENDATION_PROMPT: str

    class Config:
        env_file = ".env"

settings = Settings()
