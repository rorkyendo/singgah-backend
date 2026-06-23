"""
Base class untuk semua property source agents.
Setiap agent bertanggung jawab untuk satu sumber data (Rumah123, Pinhome, dll).
"""
from abc import ABC, abstractmethod

from app.services.base import PropertyListing, PropertyDetail


class BasePropertyAgent(ABC):
    """
    Interface standar untuk semua property agents.

    Setiap agent encapsulate:
    - URL building untuk sumber datanya
    - Scraping (via Playwright browser)
    - Parsing HTML menjadi PropertyListing / PropertyDetail
    - Fallback jika browser scraper gagal
    """

    source_name: str = ""
    supported_property_types: list[str] = ["kost", "kontrakan"]

    def supports(self, property_type: str) -> bool:
        return property_type in self.supported_property_types

    @abstractmethod
    async def search(
        self,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        """Cari listing properti berdasarkan lokasi dan budget."""
        ...

    @abstractmethod
    async def get_detail(self, url: str) -> PropertyDetail:
        """Ambil detail lengkap satu properti dari URL-nya."""
        ...
