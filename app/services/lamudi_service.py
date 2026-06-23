import logging
import re
from urllib.parse import quote

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import BaseScraper, PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.lamudi.co.id"

class LamudiScraper(BaseScraper):
    source_name = "Lamudi"

    def _location_slug(self, location: str) -> str:
        return location.strip().lower().replace(" ", "-")

    def _location_candidates(self, location: str) -> list[str]:
        """Return candidate slugs for a location.

        Lamudi redirects single-segment city slugs to province/city automatically,
        so the direct slug is usually sufficient.
        """
        slug = self._location_slug(location)
        return [slug]

    def _category_path(self, property_type: str) -> str:
        """Map property_type to Lamudi URL category."""
        t = (property_type or "kost").lower()
        if t in ("apartemen", "apartment"):
            return "apartemen"
        # Lamudi does not have kost category; fallback to rumah
        if t == "kost":
            return "rumah"
        return "rumah"

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
        candidates = self._location_candidates(location)
        category = self._category_path(property_type)
        resp = None

        for slug in candidates:
            # Lamudi URL: /sewa/{region}/{city}/{category}/
            search_url = f"{BASE_URL}/sewa/{slug}/{category}/"
            logger.info("[Lamudi] search URL: %s", search_url)
            try:
                resp = await client.get(
                    search_url,
                    headers=self._build_headers(),
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                logger.info("[Lamudi] status=%s", resp.status_code)
            except Exception as e:
                logger.warning("[Lamudi] request error: %s", e)
                continue
            if resp.status_code == 200:
                break

        if not resp or resp.status_code != 200:
            return results

        html = resp.text

        # Find all normal-listing card blocks
        # Each card starts with data-test="normal-listing"
        card_chunks = re.split(r'data-test="normal-listing"', html)
        # First chunk is before the first card, skip it
        card_chunks = card_chunks[1:]
        logger.info("[Lamudi] card chunks: %d", len(card_chunks))

        for chunk in card_chunks[:limit * 3]:
            # Only take first 5000 chars of each card to avoid overlap
            card = chunk[:5000]

            # URL: href="/properti/..." or href="/sewa/..."
            href_match = re.search(r'href="(/properti/[^"]+|/sewa/[^"]+/)"', card)
            if not href_match:
                continue
            item_url = f"{BASE_URL}{href_match.group(1)}"

            # Title: snippet__content__title with content attribute
            title_match = re.search(
                r'class="snippet__content__title"[^>]*content="([^"]+)"',
                card,
            )
            if not title_match:
                title_match = re.search(
                    r'class="snippet__content__title"[^>]*>([^<]+)<',
                    card,
                )
            title = title_match.group(1).strip() if title_match else ""

            # Location: data-test="snippet-content-location"
            loc_match = re.search(
                r'data-test="snippet-content-location">([^<]+)<',
                card,
            )
            item_location = loc_match.group(1).strip() if loc_match else location

            # Price: snippet__content__price - capture full text including M/Jt suffix
            price_match = re.search(
                r'class="snippet__content__price"[^>]*>(.*?)</div>',
                card, re.DOTALL | re.IGNORECASE,
            )
            if price_match:
                price_text = re.sub(r"<[^>]+>", "", price_match.group(1)).strip()
            else:
                price_fallback = re.search(r'Rp[\.\s\d,]+\s*(?:M|Jt|Rb|Miliar)?(?:\s*/\s*(?:bulan|tahun|malam))?', card, re.IGNORECASE)
                price_text = price_fallback.group().strip() if price_fallback else ""
            price = self._clean_price(price_text) if price_text else 0

            # Image: first <img> with lamudi URL inside snippet__image
            img_match = re.search(
                r'<img[^>]+src="(https://img\.lamudi\.com[^"]+)"',
                card,
                re.IGNORECASE,
            )
            thumbnail = img_match.group(1) if img_match else ""

            logger.info(
                "[Lamudi] card: title=%s price=%s loc=%s img=%s",
                title[:40], price, item_location[:30], bool(thumbnail),
            )

            if title and (budget_min <= price <= budget_max or price == 0):
                results.append(PropertyListing(
                    title=title,
                    price=price,
                    location=item_location,
                    property_type=property_type,
                    source=self.source_name,
                    url=item_url,
                    image_url=thumbnail,
                    images=[thumbnail] if thumbnail else [],
                ))

            if len(results) >= limit:
                break

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

            # Title
            h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
            title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""

            # Price
            price_match = re.search(r'Rp[\.\s\d,]+(?:\s*/\s*(?:bulan|tahun|malam))?', html, re.IGNORECASE)
            price = self._clean_price(price_match.group()) if price_match else 0

            # Description - try multiple patterns
            desc_match = re.search(
                r'class="[^"]*(?:description|desc-content|body-content)[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL | re.IGNORECASE,
            )
            description = re.sub(r"<[^>]+>", " ", desc_match.group(1)).strip() if desc_match else ""

            # Location
            loc_match = re.search(
                r'data-test="[^"]*location[^"]*">([^<]+)<',
                html, re.IGNORECASE,
            )
            location = loc_match.group(1).strip() if loc_match else ""

            # Images
            images = []
            for pattern in [
                r'<img[^>]+src="(https://img\.lamudi\.com[^"]+)"',
                r'<img[^>]+data-src="(https://img\.lamudi\.com[^"]+)"',
            ]:
                found = re.findall(pattern, html, re.IGNORECASE)
                for src in found:
                    if src not in images and "svg" not in src.lower() and "logo" not in src.lower():
                        images.append(src)
                if len(images) >= 10:
                    break

            logger.info("[Lamudi] detail: title=%s price=%s images=%d", title, price, len(images))

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
            logger.warning("Lamudi detail failed: %s", e)
            return PropertyDetail(title="", price=0, location="", description="", url=url, source=self.source_name)


class LamudiAgent:
    source_name = "Lamudi"

    def __init__(self):
        self.llm = OpenAI(
            api_key=settings.API_KEY,
            base_url=settings.LLM_URL,
        )
        self.scraper = LamudiScraper()

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
            f"Berikan {limit} nama properti sewa {property_type} di {location} "
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
            logger.warning("Lamudi LLM fallback failed: %s", e)
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
