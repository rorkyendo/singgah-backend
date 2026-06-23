import logging
import re
from urllib.parse import quote

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import BaseScraper, PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)


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
                    thumbnail = self._extract_thumbnail(match[0])
                    results.append(PropertyListing(
                        title=title or f"{tipe.title()} di {location}",
                        price=price,
                        location=location,
                        property_type=property_type,
                        source=self.source_name,
                        url=item_url,
                        image_url=thumbnail,
                        images=[thumbnail] if thumbnail else [],
                    ))

        except Exception:
            pass

        return results

    async def get_detail(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> PropertyDetail:
        try:
            resp = await client.get(
                url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return PropertyDetail(title="", price=0, location="", description="", url=url, source=self.source_name)

            html = resp.text
            title = re.sub(r"<[^>]+>", "", re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE).group(1)).strip() if re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE) else ""
            price_text = re.search(r'Rp\s*([\d.,]+)', html, re.IGNORECASE)
            price = self._clean_price(price_text.group(1)) if price_text else 0
            desc_match = re.search(r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
            description = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip() if desc_match else ""

            base_url = "https://www.pinhome.id"
            images = self._extract_image_urls(html, base_url, 10)

            return PropertyDetail(
                title=title,
                price=price,
                location="",
                description=description,
                images=images,
                source=self.source_name,
                url=url,
            )
        except Exception as e:
            logger.warning("Pinhome detail failed: %s", e)
            return PropertyDetail(title="", price=0, location="", description="", url=url, source=self.source_name)


class PinhomeAgent:
    source_name = "Pinhome"

    def __init__(self):
        self.llm = OpenAI(
            api_key=settings.API_KEY,
            base_url=settings.LLM_URL,
        )
        self.scraper = PinhomeScraper()

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

    async def get_detail(self, client: httpx.AsyncClient, url: str) -> PropertyDetail:
        return await self.scraper.get_detail(client, url)

    def _llm_fallback(
        self,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str,
        limit: int,
    ) -> list[PropertyListing]:
        tipe = "sewa" if property_type in ("kost", "kontrakan") else "jual"
        prompt = (
            f"Berikan {limit} nama properti {tipe} di {location} "
            f"dengan budget Rp{budget_min:,} - Rp{budget_max:,}. "
            f"Format: nama_properti, harga_per_bulan. Pisahkan dengan baris baru."
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
            logger.warning("Pinhome LLM fallback failed: %s", e)
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
