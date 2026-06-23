import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

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
    images: List[str] = field(default_factory=list)


@dataclass
class PropertyDetail:
    title: str
    price: int
    location: str
    description: str
    images: List[str] = field(default_factory=list)
    source: str = ""
    url: str = ""
    property_type: str = ""
    bedrooms: int = 0
    bathrooms: int = 0
    land_area: int = 0
    building_area: int = 0
    facilities: List[str] = field(default_factory=list)


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

    def _extract_image_urls(self, html: str, base_url: str, limit: int = 10) -> List[str]:
        urls = set()
        patterns = [
            r'<img[^>]+src="(https?://[^"]+)"[^>]*>',
            r'<img[^>]+data-src="(https?://[^"]+)"[^>]*>',
            r'<img[^>]+src="(/[^"]+)"[^>]*>',
            r'<img[^>]+data-src="(/[^"]+)"[^>]*>',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for src in matches:
                if src.startswith("/"):
                    src = base_url.rstrip("/") + src
                if src.startswith("http") and not src.endswith(".svg"):
                    urls.add(src)
        return list(urls)[:limit]

    def _extract_thumbnail(self, html: str) -> str:
        patterns = [
            r'<img[^>]+src="(https?://[^"]+)"[^>]*>',
            r'<img[^>]+data-src="(https?://[^"]+)"[^>]*>',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for src in matches:
                if src.startswith("http") and not src.endswith(".svg"):
                    return src
        return ""
