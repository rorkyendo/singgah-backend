"""
Pinhome Agent — scrapes pinhome.id via Playwright.
Data: kos di berbagai kota Indonesia.
URL pattern: /kost untuk kost, /sewa/rumah/{province}/{slug}/ untuk kontrakan.
Pinhome berat JS, wait_selector lebih panjang.
"""
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.agents.base_agent import BasePropertyAgent
from app.agents._browser import fetch_page, clean_price, first_img, parse_specs
from app.services.base import PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pinhome.id"

# Province mapping untuk URL Pinhome (provinsi/kota).
_PINHOME_PROVINCE_MAP = {
    "jakarta": "dki-jakarta",
    "jakarta-pusat": "dki-jakarta",
    "jakarta-selatan": "dki-jakarta",
    "jakarta-utara": "dki-jakarta",
    "jakarta-barat": "dki-jakarta",
    "jakarta-timur": "dki-jakarta",
    "depok": "jawa-barat",
    "bogor": "jawa-barat",
    "bekasi": "jawa-barat",
    "bandung": "jawa-barat",
    "tangerang": "banten",
    "tangerang-selatan": "banten",
    "surabaya": "jawa-timur",
    "malang": "jawa-timur",
    "yogyakarta": "di-yogyakarta",
    "semarang": "jawa-tengah",
    "medan": "sumatera-utara",
    "makassar": "sulawesi-selatan",
    "palembang": "sumatera-selatan",
}


class PinhomeAgent(BasePropertyAgent):
    source_name = "Pinhome"

    def _build_url(self, location: str, property_type: str) -> str:
        slug = location.strip().lower().replace(" ", "-")
        if property_type == "kost":
            return f"{BASE_URL}/kost"
        province = _PINHOME_PROVINCE_MAP.get(slug, slug)
        return f"{BASE_URL}/sewa/rumah/{province}/{slug}/"

    async def search(
        self,
        location: str,
        budget_min: int,
        budget_max: int,
        property_type: str = "kost",
        limit: int = 5,
    ) -> list[PropertyListing]:
        url = self._build_url(location, property_type)
        try:
            html = await fetch_page(url, wait_selector="h2, h3, [class*='card']", timeout=30000)
            if not html:
                return []
            results = self._parse(html, limit)
            # Pinhome cards are JS-rendered, so price and images often don't appear in
            # the search HTML. Fetch the detail page for each listing to fill them in.
            for listing in results:
                if (not listing.image_url or listing.price <= 0) and listing.url:
                    try:
                        detail = await self.get_detail(listing.url)
                        if detail.images:
                            listing.image_url = detail.images[0]
                            listing.images = detail.images[:5]
                        if detail.price > 0 and listing.price <= 0:
                            listing.price = detail.price
                    except Exception as e:
                        logger.warning("[Pinhome] detail enrichment failed for %s: %s", listing.url, e)
            return results
        except Exception as e:
            logger.warning("[Pinhome] search failed: %s", e)
            return []

    def _parse(self, html: str, limit: int) -> list[PropertyListing]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()

        for a in soup.find_all("a", href=re.compile(r"/(kost/kamar|disewa/rumah-sekunder/unit|sewa/rumah)/", re.I)):
            if len(results) >= limit:
                break
            href = a.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            full_url = urljoin(BASE_URL, href)

            title_el = a.find(["h2", "h3", "h4", "p"])
            title = title_el.get_text(strip=True) if title_el else a.get_text(" ", strip=True)
            if not title or len(title) < 8:
                continue

            parent = a.find_parent("div", class_=re.compile(r"card|listing|item")) or a.parent or a
            price_str = parent.find(string=re.compile(r"Rp\s*[\d]", re.I))
            price = clean_price(str(price_str)) if price_str else 0
            image = first_img(parent)
            if image and image.startswith("/"):
                image = urljoin(BASE_URL, image)

            results.append(PropertyListing(
                title=title[:120], price=price, location="", property_type="",
                source=self.source_name, url=full_url,
                image_url=image, images=[image] if image else [],
            ))
        return results

    async def get_detail(self, url: str) -> PropertyDetail:
        try:
            html = await fetch_page(url, wait_selector="h1", timeout=30000, sleep=2.5)
            if not html:
                return self._empty(url)
            soup = BeautifulSoup(html, "html.parser")
            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else ""
            price_el = soup.find(string=re.compile(r"Rp\s*[\d]", re.I))
            price = clean_price(str(price_el)) if price_el else 0
            desc_el = soup.select_one("[class*='desc'], [class*='detail'], main")
            description = desc_el.get_text(separator="\n", strip=True)[:1500] if desc_el else ""
            specs = parse_specs(soup)
            # Only take images served by Pinhome's CDN to avoid tracking pixels/logos.
            images = [img["src"] for img in soup.select("img[src]")
                      if img.get("src", "").startswith("https://img.pinhome.id/")][:8]
            return PropertyDetail(
                title=title, price=price, location="", description=description,
                images=images, source=self.source_name, url=url, **specs,
            )
        except Exception as e:
            logger.warning("[Pinhome] get_detail failed: %s", e)
            return self._empty(url)

    def _empty(self, url: str) -> PropertyDetail:
        return PropertyDetail(title="", price=0, location="", description="",
                              images=[], source=self.source_name, url=url)
