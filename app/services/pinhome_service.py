import html
import json
import logging
import re
from urllib.parse import quote

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import BaseScraper, PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pinhome.id"


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
        # Pinhome supports location via ?keyword= parameter
        # Category mapping: kost -> /kost/, kontrakan -> /sewa/rumah/
        if property_type == "kontrakan":
            path = "/sewa/rumah"
        else:
            path = "/kost"
        search_url = f"{BASE_URL}{path}/?keyword={quote(location.lower())}"

        logger.info("[Pinhome] search URL: %s", search_url)

        try:
            resp = await client.get(
                search_url,
                headers=self._build_headers(),
                timeout=self.timeout,
                follow_redirects=True,
            )
            logger.info("[Pinhome] status=%s", resp.status_code)
            if resp.status_code != 200:
                return results

            page_html = resp.text

            # Parse JSON-LD ItemList
            ld_blocks = re.findall(
                r'<script type="application/ld\+json">(.*?)</script>',
                page_html, re.DOTALL,
            )
            logger.info("[Pinhome] JSON-LD blocks: %d", len(ld_blocks))

            items = []
            for block in ld_blocks:
                try:
                    data = json.loads(block)
                    if isinstance(data, dict) and data.get("@type") == "ItemList":
                        items = data.get("itemListElement", [])
                        break
                except json.JSONDecodeError:
                    continue

            logger.info("[Pinhome] items from JSON-LD: %d", len(items))

            for item in items:
                acc = item.get("item", {})
                name = acc.get("name", "")
                item_url = acc.get("url", "")
                if item_url:
                    # Fix double slash after domain
                    item_url = item_url.replace("https://www.pinhome.id//", f"{BASE_URL}/")
                    if not item_url.startswith("http"):
                        item_url = BASE_URL + item_url
                else:
                    item_url = ""

                image = acc.get("image", "")
                offers = acc.get("offers", {})
                price = int(offers.get("price", 0)) if offers.get("price") else 0
                addr = acc.get("address", {})
                addr_locality = addr.get("addressLocality", "")
                addr_region = addr.get("addressRegion", "")
                item_location = f"{addr_locality}, {addr_region}".strip(", ")

                # Filter by budget; keyword already applied by Pinhome
                # Allow yearly rents if monthly equivalent (price/12) fits budget
                if price:
                    budget_ok = (
                        budget_min <= price <= budget_max
                        or budget_min <= price // 12 <= budget_max
                    )
                else:
                    budget_ok = True

                logger.info(
                    "[Pinhome] item: name=%s price=%s loc=%s img=%s match=%s",
                    name[:50], price, item_location[:30], bool(image), budget_ok,
                )

                if budget_ok:
                    name = html.unescape(name)
                    results.append(PropertyListing(
                        title=name or f"Kost di {location}",
                        price=price,
                        location=item_location or location,
                        property_type=property_type,
                        source=self.source_name,
                        url=item_url,
                        image_url=image,
                        images=[image] if image else [],
                    ))

                if len(results) >= limit:
                    break

        except Exception as e:
            logger.warning("[Pinhome] search error: %s", e)

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

            page_html = resp.text

            # Try JSON-LD first
            ld_blocks = re.findall(
                r'<script type="application/ld\+json">(.*?)</script>',
                page_html, re.DOTALL,
            )
            for block in ld_blocks:
                try:
                    data = json.loads(block)
                    if isinstance(data, dict) and data.get("@type") in ("Accommodation", "Residence", "Place"):
                        return PropertyDetail(
                            title=data.get("name", ""),
                            price=int(data.get("offers", {}).get("price", 0)) if data.get("offers") else 0,
                            location=data.get("address", {}).get("addressLocality", ""),
                            description=data.get("description", ""),
                            images=[data.get("image", "")] if data.get("image") else [],
                            source=self.source_name,
                            url=url,
                        )
                except (json.JSONDecodeError, ValueError):
                    continue

            # Fallback to HTML parsing
            h1 = re.search(r'<h1[^>]*>(.*?)</h1>', page_html, re.DOTALL | re.IGNORECASE)
            title = re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else ""

            price_text = re.search(r'Rp\s*([\d.,]+)', page_html, re.IGNORECASE)
            price = self._clean_price(price_text.group(1)) if price_text else 0

            desc_match = re.search(r'<div[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</div>', page_html, re.DOTALL | re.IGNORECASE)
            description = re.sub(r"<[^>]+>", " ", desc_match.group(1)).strip() if desc_match else ""

            images = self._extract_image_urls(page_html, BASE_URL, 10)

            logger.info("[Pinhome] detail: title=%s price=%s images=%d", title, price, len(images))

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
