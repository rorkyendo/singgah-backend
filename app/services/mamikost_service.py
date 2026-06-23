import json
import logging
import re

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import BaseScraper, PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://mamikos.com"
API_URL = f"{BASE_URL}/api/v1/stories/list"


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

        body = {
            "take": limit * 3,
            "page": 1,
            "keywords": location,
            "filters": {
                "keywords": location,
                "rent_type": 2,
                "price_range": [budget_min, budget_max],
                "sorting": "price",
                "sorting_direction": "-",
            },
        }

        headers = self._build_headers()
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        headers["Referer"] = f"{BASE_URL}/"

        logger.info("[Mamikost] API POST: %s", API_URL)

        try:
            resp = await client.post(
                API_URL,
                headers=headers,
                json=body,
                timeout=self.timeout,
                follow_redirects=True,
            )
            logger.info("[Mamikost] API status=%s", resp.status_code)

            if resp.status_code != 200:
                return results

            data = resp.json()
            rooms = data.get("rooms", [])
            logger.info("[Mamikost] API rooms: %d", len(rooms))

            for room in rooms:
                title = room.get("room-title", "") or room.get("area_label", "")
                share_url = room.get("share_url", "")
                item_url = share_url if share_url else ""

                price_fmt = room.get("price_title_format", {})
                price_str = price_fmt.get("price", "")
                price = self._clean_price(price_str) if price_str else 0

                photo = room.get("photo_url", {})
                thumbnail = photo.get("medium", photo.get("large", photo.get("small", "")))

                subdistrict = room.get("subdistrict", "")
                city = room.get("city", "")
                item_location = f"{subdistrict}, {city}".strip(", ")

                logger.info(
                    "[Mamikost] room: title=%s price=%s img=%s loc=%s",
                    title[:40], price, bool(thumbnail), item_location[:30],
                )

                if title and (budget_min <= price <= budget_max or price == 0):
                    results.append(PropertyListing(
                        title=title,
                        price=price,
                        location=item_location or location,
                        property_type="kost",
                        source=self.source_name,
                        url=item_url,
                        image_url=thumbnail,
                        images=[thumbnail] if thumbnail else [],
                    ))

                if len(results) >= limit:
                    break

        except Exception as e:
            logger.warning("[Mamikost] API error: %s", e)

        return results

    async def get_detail(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> PropertyDetail:
        slug_match = re.search(r'/room/([^?]+)', url)
        slug = slug_match.group(1) if slug_match else ""

        if slug:
            detail_api = f"{BASE_URL}/api/v1/stories/detail/{slug}"
            headers = self._build_headers()
            headers["Accept"] = "application/json"
            headers["Referer"] = f"{BASE_URL}/"

            try:
                resp = await client.get(
                    detail_api,
                    headers=headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                logger.info("[Mamikost] detail API status=%s", resp.status_code)

                if resp.status_code == 200:
                    data = resp.json()
                    room = data.get("room", data.get("data", {}))
                    if room:
                        title = room.get("room-title", room.get("name", ""))
                        price_fmt = room.get("price_title_format", {})
                        price = self._clean_price(price_fmt.get("price", "")) if price_fmt else 0
                        description = room.get("description", room.get("remark", ""))
                        subdistrict = room.get("subdistrict", "")
                        city = room.get("city", "")
                        location = f"{subdistrict}, {city}".strip(", ")

                        images = []
                        cards = room.get("cards", [])
                        for card in cards:
                            if isinstance(card, dict):
                                for key in ("photo_url", "url", "image"):
                                    img = card.get(key, "")
                                    if img and isinstance(img, str) and "static.mamikos.com" in img:
                                        images.append(img)
                                    elif isinstance(img, dict):
                                        for sz in ("large", "medium", "small"):
                                            if img.get(sz):
                                                images.append(img[sz])
                                                break

                        if not images:
                            photo = room.get("photo_url", {})
                            if photo:
                                for sz in ("large", "medium", "small"):
                                    if photo.get(sz):
                                        images.append(photo[sz])
                                        break

                        logger.info("[Mamikost] detail: title=%s price=%s images=%d", title, price, len(images))

                        return PropertyDetail(
                            title=title,
                            price=price,
                            location=location,
                            description=description,
                            images=images[:10],
                            source=self.source_name,
                            url=url,
                        )
            except Exception as e:
                logger.warning("[Mamikost] detail API error: %s", e)

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

            h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
            title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""

            price_text = re.search(r'Rp\s*([\d.,]+)', html, re.IGNORECASE)
            price = self._clean_price(price_text.group(1)) if price_text else 0

            desc_match = re.search(
                r'<(?:div|p)[^>]*class="[^"]*(?:desc|description|kost-desc|room-desc)[^"]*"[^>]*>(.*?)</(?:div|p)>',
                html, re.DOTALL | re.IGNORECASE
            )
            description = re.sub(r"<[^>]+>", " ", desc_match.group(1)).strip() if desc_match else ""

            images = []
            for pattern in [
                r'<img[^>]+data-src="(https?://[^"]+)"',
                r'<img[^>]+data-lazy-src="(https?://[^"]+)"',
                r'<img[^>]+src="(https?://[^"]+)"',
            ]:
                found = re.findall(pattern, html, re.IGNORECASE)
                for src in found:
                    if src not in images and not src.endswith(".svg") and "icon" not in src.lower():
                        images.append(src)
                if len(images) >= 10:
                    break

            logger.info("[Mamikost] detail HTML: title=%s price=%s images=%d", title, price, len(images))

            return PropertyDetail(
                title=title,
                price=price,
                location="",
                description=description,
                images=images[:10],
                source=self.source_name,
                url=url,
            )
        except Exception as e:
            logger.warning("Mamikost detail failed: %s", e)
            return PropertyDetail(title="", price=0, location="", description="", url=url, source=self.source_name)


class MamikostAgent:
    source_name = "Mamikost"

    def __init__(self):
        self.llm = OpenAI(
            api_key=settings.API_KEY,
            base_url=settings.LLM_URL,
        )
        self.scraper = MamikostScraper()

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
        prompt = (
            f"Berikan {limit} nama kost di {location} "
            f"dengan budget Rp{budget_min:,} - Rp{budget_max:,}. "
            f"Format: nama_kost, harga_per_bulan. Pisahkan dengan baris baru."
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
            logger.warning("Mamikost LLM fallback failed: %s", e)
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
                property_type="kost",
                source=self.source_name,
                url="",
            ))

        return listings[:limit]
