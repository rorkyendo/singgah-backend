import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Infrastructure config — loaded from .env only."""
    DATABASE_URL: str
    PROJECT_NAME: str
    API_KEY: str
    LLM_MODEL: str
    LLM_URL: str
    CORS_ORIGINS: str = "*"

    # Legacy prompt fields — kept for backward compat with orchestrator_controller.
    # New code should use prompts.get(lang, key) instead.
    SYSTEM_PROMPT: str = ""
    GREETING_PROMPT: str = ""
    FILTER_PROMPT: str = ""
    CHECK_INTENT_PROMPT: str = ""
    CONDITIONAL_PROMPT: str = ""
    RECOMMENDATION_PROMPT: str = ""
    CHECK_RECOMENDATION_PROMPT: str = ""
    SYSTEM_PROMPT_EN: str = ""
    GREETING_PROMPT_EN: str = ""
    FILTER_PROMPT_EN: str = ""
    CHECK_INTENT_PROMPT_EN: str = ""
    CONDITIONAL_PROMPT_EN: str = ""
    RECOMMENDATION_PROMPT_EN: str = ""
    CHECK_RECOMENDATION_PROMPT_EN: str = ""

    class Config:
        env_file = ".env"


class PromptConfig:
    """
    Loads all LLM prompts from prompts_config.yaml.

    Usage:
        prompts.get("id", "system")
        prompts.get("en", "greeting")
        prompts.format("id", "expand_location", property_type="kost", location="Jakarta")
    """

    _YAML_PATH = Path(__file__).parent.parent.parent / "prompts_config.yaml"

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self):
        if not self._YAML_PATH.exists():
            raise FileNotFoundError(f"prompts_config.yaml not found at {self._YAML_PATH}")
        with open(self._YAML_PATH, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}

    def get(self, lang: str, key: str) -> str:
        """Return prompt for language + key. Falls back to 'id' if lang not found."""
        lang = (lang or "id").lower()
        lang_data = self._data.get(lang) or self._data.get("id", {})
        return (lang_data.get(key) or "").strip()

    def format(self, lang: str, key: str, **kwargs) -> str:
        """Return prompt with .format(**kwargs) applied."""
        return self.get(lang, key).format(**kwargs)


settings = Settings()
prompts = PromptConfig()
