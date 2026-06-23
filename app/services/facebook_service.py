import json
import logging
import re
from urllib.parse import quote

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import BaseScraper, PropertyListing

logger = logging.getLogger(__name__)


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


class FacebookAgent:
    source_name = "Facebook Marketplace"

    def __init__(self):
        self.llm = OpenAI(
            api_key=settings.API_KEY,
            base_url=settings.LLM_URL,
        )
        self.scraper = FacebookMarketplaceScraper()

    async def search_and_analyze(
        self,
        client: httpx.AsyncClient,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 3,
    ) -> list[PropertyListing]:
        listings = await self.scraper.search(
            client, location, budget_min, budget_max, property_type, limit,
        )

        if not listings:
            listings = self._llm_fallback(location, budget_min, budget_max, property_type, limit)

        return listings

    def _llm_fallback(
        self,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str,
        limit: int,
    ) -> list[PropertyListing]:
        prompt = (
            f"Berikan {limit} nama {property_type} di {location} "
            f"dengan budget Rp{budget_min:,} - Rp{budget_max:,} "
            f"yang mungkin ditemukan di Facebook Marketplace. "
            f"Format: nama_tempat, harga_per_bulan. Pisahkan dengan baris baru."
        )

        try:
            response = self.llm.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": settings.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=300,
                stream=False,
            )
            text = response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Facebook LLM fallback failed: %s", e)
            return []

        listings: list[PropertyListing] = []
        for line in text.split("\n"):
            line = line.strip().lstrip("-•*0123456789. ")
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            name = parts[0] if parts else line
            price = self.scraper._clean_price(parts[1]) if len(parts) > 1 else 0

            listings.append(PropertyListing(
                title=name,
                price=price if price else budget_min,
                location=location,
                property_type=property_type,
                source=self.source_name,
                url="",
            ))

        return listings[:limit]
