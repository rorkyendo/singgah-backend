import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote

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


class OLXScraper(BaseScraper):
    source_name = "OLX"

    async def search(
        self,
        client: httpx.AsyncClient,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        results: list[PropertyListing] = []
        query = f"{property_type} {location}"
        encoded_query = quote(query)
        encoded_location = quote(location)

        url = (
            f"https://www.olx.co.id/properti/rumah/q-{encoded_query}/"
            f"?search%5Bfilter_float_price:from%5D={budget_min}"
            f"&search%5Bfilter_float_price:to%5D={budget_max}"
        )

        try:
            resp = await client.get(
                url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return results

            html = resp.text
            listing_pattern = re.findall(
                r'<a[^>]*href="(/item/[^"]+)"[^>]*>.*?'
                r'<h2[^>]*>(.*?)</h2>.*?'
                r'<span[^>]*class="[^"]*price[^"]*"[^>]*>(.*?)</span>',
                html,
                re.DOTALL | re.IGNORECASE,
            )

            for match in listing_pattern[:limit]:
                item_url = f"https://www.olx.co.id{match[0]}"
                title = re.sub(r"<[^>]+>", "", match[1]).strip()
                price_text = re.sub(r"<[^>]+>", "", match[2]).strip()
                price = self._clean_price(price_text)

                if budget_min <= price <= budget_max or price == 0:
                    results.append(PropertyListing(
                        title=title or f"{property_type.title()} di {location}",
                        price=price,
                        location=location,
                        property_type=property_type,
                        source=self.source_name,
                        url=item_url,
                    ))

        except Exception:
            pass

        return results


class MamikostScraper(BaseScraper):
    source_name = "Mamikost"

    async def search(
        self,
        client: httpx.AsyncClient,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        results: list[PropertyListing] = []
        encoded_location = quote(location)
        url = f"https://mamikos.com/cari/{encoded_location}/kost"

        try:
            resp = await client.get(
                url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return results

            html = resp.text
            cards = re.findall(
                r'<a[^>]*href="(/room/[^"]+)"[^>]*>.*?'
                r'<h[23][^>]*>(.*?)</h[23]>.*?'
                r'Rp\s*([\d.,]+)',
                html,
                re.DOTALL | re.IGNORECASE,
            )

            for match in cards[:limit]:
                item_url = f"https://mamikos.com{match[0]}"
                title = re.sub(r"<[^>]+>", "", match[1]).strip()
                price = self._clean_price(match[2])

                if budget_min <= price <= budget_max or price == 0:
                    results.append(PropertyListing(
                        title=title or f"Kost di {location}",
                        price=price,
                        location=location,
                        property_type="kost",
                        source=self.source_name,
                        url=item_url,
                    ))

        except Exception:
            pass

        return results


class PinhomeScraper(BaseScraper):
    source_name = "Pinhome"

    async def search(
        self,
        client: httpx.AsyncClient,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        results: list[PropertyListing] = []
        encoded_location = quote(location)
        tipe = "sewa" if property_type in ("kost", "kontrakan") else "jual"
        url = f"https://www.pinhome.id/{tipe}/rumah/{encoded_location}"

        try:
            resp = await client.get(
                url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return results

            html = resp.text
            cards = re.findall(
                r'<a[^>]*href="(/properti/[^"]+)"[^>]*>.*?'
                r'<h[23][^>]*>(.*?)</h[23]>.*?'
                r'Rp\s*([\d.,]+)',
                html,
                re.DOTALL | re.IGNORECASE,
            )

            for match in cards[:limit]:
                item_url = f"https://www.pinhome.id{match[0]}"
                title = re.sub(r"<[^>]+>", "", match[1]).strip()
                price = self._clean_price(match[2])

                if budget_min <= price <= budget_max or price == 0:
                    results.append(PropertyListing(
                        title=title or f"{tipe.title()} di {location}",
                        price=price,
                        location=location,
                        property_type=property_type,
                        source=self.source_name,
                        url=item_url,
                    ))

        except Exception:
            pass

        return results


class FacebookMarketplaceScraper(BaseScraper):
    source_name = "Facebook Marketplace"

    async def search(
        self,
        client: httpx.AsyncClient,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        results: list[PropertyListing] = []
        encoded_query = quote(f"{property_type} {location}")
        url = (
            f"https://www.facebook.com/marketplace/{location}/search/"
            f"?query={encoded_query}"
            f"&minPrice={budget_min}"
            f"&maxPrice={budget_max}"
        )

        try:
            resp = await client.get(
                url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return results

            html = resp.text
            script_data = re.findall(
                r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
                html,
                re.DOTALL,
            )

            for script in script_data:
                try:
                    data = json.loads(script)
                    marketplace_items = self._extract_items(data, limit)
                    results.extend(marketplace_items)
                    if len(results) >= limit:
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

        except Exception:
            pass

        return results[:limit]

    def _extract_items(self, data: dict, limit: int) -> list[PropertyListing]:
        results: list[PropertyListing] = []

        def _walk(obj, depth=0):
            if depth > 10 or len(results) >= limit:
                return
            if isinstance(obj, dict):
                if "marketplace_listing_title" in str(obj) or "listing" in str(obj).lower():
                    for key in obj:
                        val = obj[key]
                        if isinstance(val, dict):
                            title = val.get("marketplace_listing_title", "") or val.get("title", "") or val.get("name", "")
                            price_str = val.get("listing_price", "") or val.get("price", "")
                            if title and isinstance(title, str):
                                price = self._safe_int(str(price_str)) if price_str else 0
                                results.append(PropertyListing(
                                    title=str(title)[:100],
                                    price=price,
                                    location="",
                                    property_type="",
                                    source=self.source_name,
                                    url="",
                                ))
                for key, val in obj.items():
                    _walk(val, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item, depth + 1)

        _walk(data)
        return results


class LamudiScraper(BaseScraper):
    source_name = "Lamudi"

    async def search(
        self,
        client: httpx.AsyncClient,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        results: list[PropertyListing] = []
        encoded_location = quote(location)
        encoded_query = quote(f"{property_type} {location}")
        url = (
            f"https://www.lamudi.co.id/search/"
            f"?q={encoded_query}"
            f"&type=rent"
            f"&price_min={budget_min}"
            f"&price_max={budget_max}"
        )

        try:
            resp = await client.get(
                url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return results

            html = resp.text
            cards = re.findall(
                r'<a[^>]*href="(/property/[^"]+)"[^>]*>.*?'
                r'<h[23][^>]*>(.*?)</h[23]>.*?'
                r'Rp\s*([\d.,]+)',
                html,
                re.DOTALL | re.IGNORECASE,
            )

            for match in cards[:limit]:
                item_url = f"https://www.lamudi.co.id{match[0]}"
                title = re.sub(r"<[^>]+>", "", match[1]).strip()
                price = self._clean_price(match[2])

                if budget_min <= price <= budget_max or price == 0:
                    results.append(PropertyListing(
                        title=title or f"{property_type.title()} di {location}",
                        price=price,
                        location=location,
                        property_type=property_type,
                        source=self.source_name,
                        url=item_url,
                    ))

        except Exception:
            pass

        return results


async def run_all_scrapers(
    location: str,
    budget_min: int,
    budget_max: int,
    property_type: str = "kost",
    limit_per_source: int = 3,
) -> list[PropertyListing]:
    scrapers: list[BaseScraper] = [
        OLXScraper(),
        MamikostScraper(),
        PinhomeScraper(),
        LamudiScraper(),
        FacebookMarketplaceScraper(),
    ]

    async with httpx.AsyncClient() as client:
        tasks = [
            scraper.search(client, location, budget_min, budget_max, property_type, limit_per_source)
            for scraper in scrapers
        ]
        results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[PropertyListing] = []
    for result in results_per_source:
        if isinstance(result, list):
            all_results.extend(result)

    all_results.sort(key=lambda x: x.price if x.price > 0 else float("inf"))
    return all_results
