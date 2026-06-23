"""
Mamikost Agent — scrapes mamikost.com via Playwright.
Data: kost di berbagai kota Indonesia.
URL pattern: /{slug} untuk listing kota.
Listing ada di link /kos/ dalam HTML (window.events hanya berisi promo/banner).
"""
import logging
import re

from bs4 import BeautifulSoup

from app.agents.base_agent import BasePropertyAgent
from app.agents._browser import fetch_page, clean_price, first_img, parse_specs
from app.services.base import PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://mamikost.com"


class MamikostAgent(BasePropertyAgent):
    source_name = "Mamikost"
    supported_property_types = ["kost"]

    def _build_url(self, location: str, property_type: str) -> str:
        slug = location.strip().lower().replace(" ", "-")
        return f"{BASE_URL}/{slug}"

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
            html = await fetch_page(url, wait_selector="[class*='title'], h2, h3, a")
            if not html:
                return []
            return self._parse(html, limit)
        except Exception as e:
            logger.warning("[Mamikost] search failed: %s", e)
            return []

    def _parse(self, html: str, limit: int) -> list[PropertyListing]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()

        for a in soup.find_all("a", href=re.compile(r"/kos/", re.I)):
            if len(results) >= limit:
                break
            href = a["href"]
            if href in seen:
                continue
            seen.add(href)
            full_url = href if href.startswith("http") else BASE_URL + href

            title_el = a.find(["h2", "h3", "h4", "span", "p"])
            title = title_el.get_text(strip=True) if title_el else a.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            parent = a.parent or a
            price_str = parent.find(string=re.compile(r"Rp\s*[\d]", re.I))
            price = clean_price(str(price_str)) if price_str else 0
            image = first_img(a) or first_img(parent)

            results.append(PropertyListing(
                title=title[:120], price=price, location="", property_type="kost",
                source=self.source_name, url=full_url,
                image_url=image, images=[image] if image else [],
            ))
        return results

    async def get_detail(self, url: str) -> PropertyDetail:
        try:
            html = await fetch_page(url, wait_selector="h1", timeout=25000)
            if not html:
                return self._empty(url)
            soup = BeautifulSoup(html, "html.parser")
            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else ""
            price_el = soup.find(string=re.compile(r"Rp\s*[\d]", re.I))
            price = clean_price(str(price_el)) if price_el else 0
            desc_el = soup.select_one("[class*='desc'], [class*='detail'], [class*='info']")
            description = desc_el.get_text(separator="\n", strip=True)[:1500] if desc_el else ""
            specs = parse_specs(soup)
            images = [img["src"] for img in soup.select("img[src]")
                      if img.get("src", "").startswith("http")][:8]
            return PropertyDetail(
                title=title, price=price, location="", description=description,
                images=images, source=self.source_name, url=url, **specs,
            )
        except Exception as e:
            logger.warning("[Mamikost] get_detail failed: %s", e)
            return self._empty(url)

    def _empty(self, url: str) -> PropertyDetail:
        return PropertyDetail(title="", price=0, location="", description="",
                              images=[], source=self.source_name, url=url)
