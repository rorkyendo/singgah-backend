import json
import logging
import re
from urllib.parse import unquote

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import BaseScraper, PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.rumah123.com"

# Location slug map for Rumah123 URL patterns
LOCATION_SLUG_MAP: dict[str, str] = {
    "gambir": "jakarta-pusat",
    "jakarta pusat": "jakarta-pusat",
    "jakarta selatan": "jakarta-selatan",
    "jakarta barat": "jakarta-barat",
    "jakarta timur": "jakarta-timur",
    "jakarta utara": "jakarta-utara",
    "jakarta": "dki-jakarta",
    "depok": "depok",
    "bogor": "bogor",
    "bekasi": "bekasi",
    "tangerang": "tangerang",
    "bandung": "bandung",
    "yogyakarta": "yogyakarta",
    "surabaya": "surabaya",
    "semarang": "semarang",
}


class Rumah123Scraper(BaseScraper):
    source_name = "Rumah123"

    def _location_slug(self, location: str) -> str:
        key = location.strip().lower()
        if key in LOCATION_SLUG_MAP:
            return LOCATION_SLUG_MAP[key]
        for k, v in LOCATION_SLUG_MAP.items():
            if k in key or key in k:
                return v
        return location.strip().lower().replace(" ", "-")

    def _decode_srcset_url(self, srcset: str) -> str:
        """Extract actual image URL from Rumah123 srcset/portal-img pattern."""
        # Pattern: /portal-img/_next/image/?url=https%3A%2F%2Fpicture.rumah123.com%2F...&w=1200&q=85
        m = re.search(r'url=([^&]+)', srcset)
        if m:
            return unquote(m.group(1))
        return srcset

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
        slug = self._location_slug(location)
        # Use /sewa/ for rent, /jual/ for sale
        search_url = f"{BASE_URL}/sewa/{slug}/rumah/"
        logger.info("[Rumah123] search URL: %s", search_url)

        try:
            resp = await client.get(
                search_url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            logger.info("[Rumah123] status=%s", resp.status_code)

            if resp.status_code != 200:
                # Try /jual/ as fallback
                search_url = f"{BASE_URL}/jual/{slug}/rumah/"
                logger.info("[Rumah123] fallback to jual URL: %s", search_url)
                resp = await client.get(
                    search_url,
                    headers=self._build_headers(),
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                logger.info("[Rumah123] fallback status=%s", resp.status_code)
                if resp.status_code != 200:
                    return results

            html = resp.text

            # Parse JSON-LD ItemList for structured data
            ld_blocks = re.findall(
                r'<script type="application/ld\+json">(.*?)</script>',
                html, re.DOTALL,
            )
            jsonld_items: list[dict] = []
            for block in ld_blocks:
                try:
                    data = json.loads(block)
                    if data.get("@type") == "ItemList":
                        jsonld_items = data.get("itemListElement", [])
                        break
                except json.JSONDecodeError:
                    continue

            logger.info("[Rumah123] JSON-LD items: %d", len(jsonld_items))

            # Build a map of url -> jsonld data
            jsonld_map: dict[str, dict] = {}
            for item in jsonld_items:
                acc = item.get("item", item)
                url = acc.get("url", "")
                if url:
                    # Normalize to path only
                    path = url.replace(BASE_URL, "")
                    jsonld_map[path] = acc

            # Find all property links in HTML
            prop_links = re.findall(r'href="(/properti/[^"]+)"', html)
            # Deduplicate
            seen = set()
            unique_links = []
            for link in prop_links:
                if link not in seen:
                    seen.add(link)
                    unique_links.append(link)

            logger.info("[Rumah123] property links: %d", len(unique_links))

            for link in unique_links[:limit * 3]:
                item_url = f"{BASE_URL}{link}"

                # Get data from JSON-LD if available
                jld = jsonld_map.get(link, {})
                title = jld.get("name", "")
                addr = jld.get("address", {})
                item_location = addr.get("addressLocality", "") if addr else ""

                # Image from JSON-LD or srcset
                thumbnail = ""
                jld_image = jld.get("image", "")
                if isinstance(jld_image, list) and jld_image:
                    thumbnail = jld_image[0]
                elif isinstance(jld_image, str):
                    thumbnail = jld_image

                # If no image from JSON-LD, find from srcset near link
                if not thumbnail:
                    link_pos = html.find(f'href="{link}"')
                    nearby = html[max(0, link_pos - 3000):link_pos + 1000]
                    srcset_match = re.search(
                        r'srcset="([^"]+)"',
                        nearby, re.IGNORECASE,
                    )
                    if srcset_match:
                        thumbnail = self._decode_srcset_url(srcset_match.group(1))

                # Price: find near link in HTML
                if not title:
                    # Fallback: extract from URL slug
                    slug_part = link.split("/properti/")[-1].rstrip("/")
                    # Remove hos/hor ID suffix
                    slug_part = re.sub(r'-hos\d+$', '', slug_part)
                    slug_part = re.sub(r'-hor\d+$', '', slug_part)
                    title = slug_part.replace("-", " ").title()

                # Price: find data-testid="ldp-text-price" before link
                link_pos = html.find(f'href="{link}"')
                nearby_before = html[max(0, link_pos - 2000):link_pos]
                price_match = re.search(
                    r'data-testid="ldp-text-price"[^>]*>([^<]+)<',
                    nearby_before, re.IGNORECASE,
                )
                price_text = price_match.group(1).strip() if price_match else ""
                price = self._clean_price(price_text) if price_text else 0

                logger.info(
                    "[Rumah123] item: title=%s price=%s img=%s",
                    title[:50], price, bool(thumbnail),
                )

                if title:
                    results.append(PropertyListing(
                        title=title,
                        price=price,
                        location=item_location or location,
                        property_type=property_type,
                        source=self.source_name,
                        url=item_url,
                        image_url=thumbnail,
                        images=[thumbnail] if thumbnail else [],
                    ))

                if len(results) >= limit:
                    break

        except Exception as e:
            logger.warning("[Rumah123] search error: %s", e)

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

            # Parse JSON-LD on detail page
            ld_blocks = re.findall(
                r'<script type="application/ld\+json">(.*?)</script>',
                html, re.DOTALL,
            )
            title = ""
            price = 0
            location = ""
            description = ""
            images: list[str] = []

            for block in ld_blocks:
                try:
                    data = json.loads(block)
                    t = data.get("@type", "")
                    if t in ("SingleFamilyResidence", "House", "Apartment", "Residence"):
                        title = data.get("name", "")
                        addr = data.get("address", {})
                        location = addr.get("addressLocality", "") if addr else ""
                        img = data.get("image", [])
                        if isinstance(img, list):
                            images = img[:10]
                        elif isinstance(img, str):
                            images = [img]
                        offers = data.get("offers", {})
                        if offers:
                            price = self._clean_price(offers.get("price", ""))
                        desc = data.get("description", "")
                        if desc:
                            description = desc
                except json.JSONDecodeError:
                    continue

            # Fallback: HTML parsing
            if not title:
                h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
                title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""

            if price == 0:
                price_match = re.search(
                    r'Rp\s*([\d.,]+\s*(?:Juta|Miliar|jt|M)?(?:\s*/\s*(?:tahun|bulan))?)',
                    html, re.IGNORECASE,
                )
                price = self._clean_price(price_match.group()) if price_match else 0

            if not description:
                desc_match = re.search(
                    r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>',
                    html, re.DOTALL | re.IGNORECASE,
                )
                description = re.sub(r"<[^>]+>", " ", desc_match.group(1)).strip() if desc_match else ""

            # Images from srcset
            if not images:
                srcset_matches = re.findall(r'srcset="([^"]+)"', html, re.IGNORECASE)
                for ss in srcset_matches:
                    img_url = self._decode_srcset_url(ss)
                    if "picture.rumah123.com" in img_url and img_url not in images:
                        images.append(img_url)
                    if len(images) >= 10:
                        break

            logger.info("[Rumah123] detail: title=%s price=%s images=%d", title, price, len(images))

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
            logger.warning("Rumah123 detail failed: %s", e)
            return PropertyDetail(title="", price=0, location="", description="", url=url, source=self.source_name)


# Keep old names for backward compatibility
OLXScraper = Rumah123Scraper


class OLXAgent:
    source_name = "Rumah123"

    def __init__(self):
        self.llm = OpenAI(
            api_key=settings.API_KEY,
            base_url=settings.LLM_URL,
        )
        self.scraper = Rumah123Scraper()

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
            f"Berikan {limit} nama tempat {property_type} di {location} "
            f"dengan budget Rp{budget_min:,} - Rp{budget_max:,}. "
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
            logger.warning("Rumah123 LLM fallback failed: %s", e)
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
