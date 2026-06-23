import logging
import re
from urllib.parse import quote

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import BaseScraper, PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://mamikos.com"

# Pre-built slug map for common Jakarta areas
LOCATION_SLUG_MAP: dict[str, str] = {
    "gambir": "gambir-kota-jakarta-pusat-daerah-khusus-ibukota-jakarta-indonesia",
    "jakarta pusat": "kota-jakarta-pusat-daerah-khusus-ibukota-jakarta-indonesia",
    "jakarta selatan": "kota-jakarta-selatan-daerah-khusus-ibukota-jakarta-indonesia",
    "jakarta barat": "kota-jakarta-barat-daerah-khusus-ibukota-jakarta-indonesia",
    "jakarta timur": "kota-jakarta-timur-daerah-khusus-ibukota-jakarta-indonesia",
    "jakarta utara": "kota-jakarta-utara-daerah-khusus-ibukota-jakarta-indonesia",
    "depok": "kota-depok-jawa-barat-indonesia",
    "bogor": "kota-bogor-jawa-barat-indonesia",
    "bekasi": "kota-bekasi-jawa-barat-indonesia",
    "tangerang": "kota-tangerang-banten-indonesia",
    "bandung": "kota-bandung-jawa-barat-indonesia",
    "yogyakarta": "kota-yogyakarta-daerah-istimewa-yogyakarta-indonesia",
    "surabaya": "kota-surabaya-jawa-timur-indonesia",
    "semarang": "kota-semarang-jawa-tengah-indonesia",
}


class MamikostScraper(BaseScraper):
    source_name = "Mamikost"

    def _location_slug(self, location: str) -> str:
        key = location.strip().lower()
        if key in LOCATION_SLUG_MAP:
            return LOCATION_SLUG_MAP[key]
        # Check partial match
        for k, v in LOCATION_SLUG_MAP.items():
            if k in key or key in k:
                return v
        # Fallback: lower + spaces to hyphens
        return key.replace(" ", "-")

    def _build_search_url(self, location: str, budget_min: int, budget_max: int) -> str:
        slug = self._location_slug(location)
        price_to = budget_max + 1000
        return (
            f"{BASE_URL}/cari/{slug}/all/bulanan/0-{price_to}/1"
            f"?keyword={quote(location)}&suggestion_type=search&rent=2"
            f"&sort=price,-&price=0-{price_to}&singgahsini=0"
        )

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
        url = self._build_search_url(location, budget_min, budget_max)
        logger.info("[Mamikost] search URL: %s", url)

        try:
            resp = await client.get(
                url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            logger.info("[Mamikost] status=%s", resp.status_code)
            if resp.status_code != 200:
                return results

            html = resp.text

            # Extract card blocks: <div ... class="kost-rc" ...>
            # Each card contains a room link, name and price
            card_blocks = re.findall(
                r'<div[^>]*class="[^"]*kost-rc[^"]*"[^>]*>(.*?)</div>\s*</div>',
                html,
                re.DOTALL | re.IGNORECASE,
            )
            logger.info("[Mamikost] card_blocks found: %d", len(card_blocks))

            if not card_blocks:
                # Fallback: look for room hrefs with nearby price
                card_blocks_raw = re.findall(
                    r'(<a[^>]*href="(/room/[^"?]+)[^"]*"[^>]*>.*?</a>)',
                    html,
                    re.DOTALL | re.IGNORECASE,
                )
                logger.info("[Mamikost] fallback room anchors: %d", len(card_blocks_raw))
                for raw_anchor, path in card_blocks_raw[:limit * 2]:
                    item_url = f"{BASE_URL}{path}"
                    title_match = re.search(r'<(?:h[1-6]|p|span|div)[^>]*>([^<]{5,})</(?:h[1-6]|p|span|div)>', raw_anchor, re.IGNORECASE)
                    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
                    price_match = re.search(r'Rp\s*([\d.,]+)', raw_anchor, re.IGNORECASE)
                    price = self._clean_price(price_match.group(1)) if price_match else 0
                    img_match = re.search(r'<img[^>]+(?:src|data-src)="(https?://[^"]+)"[^>]*>', raw_anchor, re.IGNORECASE)
                    thumbnail = img_match.group(1) if img_match else ""
                    if title and (budget_min <= price <= budget_max or price == 0):
                        results.append(PropertyListing(
                            title=title,
                            price=price,
                            location=location,
                            property_type="kost",
                            source=self.source_name,
                            url=item_url,
                            image_url=thumbnail,
                            images=[thumbnail] if thumbnail else [],
                        ))
                        if len(results) >= limit:
                            break
                return results

            for block in card_blocks[:limit]:
                # Room URL
                url_match = re.search(r'href="(/room/[^"?]+)', block, re.IGNORECASE)
                if not url_match:
                    url_match = re.search(r'href="(https?://mamikos\.com/room/[^"?]+)', block, re.IGNORECASE)
                if not url_match:
                    continue
                path = url_match.group(1)
                item_url = path if path.startswith("http") else f"{BASE_URL}{path}"

                # Title
                title_match = re.search(r'<(?:h[1-6]|p|span)[^>]*class="[^"]*(?:name|title|kost-name)[^"]*"[^>]*>(.*?)</(?:h[1-6]|p|span)>', block, re.DOTALL | re.IGNORECASE)
                if not title_match:
                    title_match = re.search(r'<(?:h[1-6])[^>]*>(.*?)</(?:h[1-6])>', block, re.DOTALL | re.IGNORECASE)
                title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""

                # Price
                price_match = re.search(r'Rp\s*([\d.,]+)', block, re.IGNORECASE)
                price = self._clean_price(price_match.group(1)) if price_match else 0

                # Thumbnail
                img_match = re.search(
                    r'<img[^>]+(?:src|data-src|data-lazy-src)="(https?://[^"]+)"[^>]*>',
                    block,
                    re.IGNORECASE,
                )
                thumbnail = img_match.group(1) if img_match else ""

                logger.info(
                    "[Mamikost] card: title=%s price=%s url=%s image=%s",
                    title, price, item_url, thumbnail,
                )

                if budget_min <= price <= budget_max or price == 0:
                    results.append(PropertyListing(
                        title=title or f"Kost di {location}",
                        price=price,
                        location=location,
                        property_type="kost",
                        source=self.source_name,
                        url=item_url,
                        image_url=thumbnail,
                        images=[thumbnail] if thumbnail else [],
                    ))

        except Exception as e:
            logger.warning("[Mamikost] search error: %s", e)

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

            h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
            title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""

            price_text = re.search(r'Rp\s*([\d.,]+)', html, re.IGNORECASE)
            price = self._clean_price(price_text.group(1)) if price_text else 0

            # Description: try multiple class patterns
            desc_match = re.search(
                r'<(?:div|p)[^>]*class="[^"]*(?:desc|description|kost-desc|room-desc)[^"]*"[^>]*>(.*?)</(?:div|p)>',
                html, re.DOTALL | re.IGNORECASE
            )
            description = re.sub(r"<[^>]+>", " ", desc_match.group(1)).strip() if desc_match else ""

            # Images: prefer data-src (lazy loaded)
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

            logger.info("[Mamikost] detail: title=%s price=%s images=%d", title, price, len(images))

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
