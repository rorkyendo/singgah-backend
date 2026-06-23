import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass
class PropertyListing:
    title: str
    price: int
    location: str
    property_type: str
    source: str
    url: str
    image_url: str = ""
    description: str = ""
    bedrooms: int = 0
    bathrooms: int = 0
    land_area: int = 0
    building_area: int = 0


class BaseScraper(ABC):
    source_name: str = ""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    @abstractmethod
    async def search(
        self,
        client: httpx.AsyncClient,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        ...

    def _safe_int(self, text: str) -> int:
        digits = re.sub(r"[^\d]", "", str(text))
        return int(digits) if digits else 0

    def _clean_price(self, text: str) -> int:
        text = text.lower().replace("rp", "").replace(".", "").replace(",", "").strip()
        digits = re.sub(r"[^\d]", "", text)
        val = int(digits) if digits else 0
        if val < 1000:
            val *= 1_000_000
        return val

    def _build_headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        }
