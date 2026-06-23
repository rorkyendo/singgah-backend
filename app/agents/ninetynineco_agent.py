"""
99.co Agent — scrapes 99.co/id via Playwright.
Data: kost & hunian sewa.
URL pattern: /id/sewa/{category}/{slug}/
Listing ada di <h2> lalu cari parent <a> atau parent card.
Harga paling akurat dari slug URL (pola: disewa-{angka}{unit}).
"""
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.agents.base_agent import BasePropertyAgent
from app.agents._browser import fetch_page, clean_price, first_img, parse_specs
from app.services.base import PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.99.co"


class NinetyNineCoAgent(BasePropertyAgent):
    source_name = "99.co"

    def _build_url(self, location: str, property_type: str) -> str:
        slug = location.strip().lower().replace(" ", "-")
        category = "kost" if property_type == "kost" else "rumah"
        return f"{BASE_URL}/id/sewa/{category}/{slug}/"

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
            html = await fetch_page(url, wait_selector="h2")
            if not html:
                return []
            return self._parse(html, limit)
        except Exception as e:
            logger.warning("[99.co] search failed: %s", e)
            return []

    def _parse(self, html: str, limit: int) -> list[PropertyListing]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()

        for card in soup.find_all("div", class_=re.compile(r"^cardSecondary\b")):
            if len(results) >= limit:
                break
            a = card.find("a", href=re.compile(r"/properti/"))
            if not a:
                continue
            href = a.get("href", "")
            if href in seen or not href:
                continue
            seen.add(href)

            title = a.get("title", "").strip()
            if not title:
                h_el = a.find(["h2", "h3", "h4"]) or card.find(["h2", "h3", "h4"])
                title = h_el.get_text(strip=True) if h_el else a.get_text(" ", strip=True)
            if not title or len(title) < 5:
                continue

            price_str = card.find(string=re.compile(r"Rp\s*[\d]", re.I))
            price = clean_price(str(price_str)) if price_str else 0
            image = first_img(card)
            if image and image.startswith("/"):
                image = urljoin(BASE_URL, image)
            full_url = href if href.startswith("http") else urljoin(BASE_URL, href)

            results.append(PropertyListing(
                title=title[:120], price=price, location="", property_type="",
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
            desc_el = soup.select_one("[class*='desc'], [class*='Description'], article")
            description = desc_el.get_text(separator="\n", strip=True)[:1500] if desc_el else ""
            specs = parse_specs(soup)
            images = [img["src"] for img in soup.select("img[src]")
                      if img.get("src", "").startswith("http")][:8]
            return PropertyDetail(
                title=title, price=price, location="", description=description,
                images=images, source=self.source_name, url=url, **specs,
            )
        except Exception as e:
            logger.warning("[99.co] get_detail failed: %s", e)
            return self._empty(url)

    def _empty(self, url: str) -> PropertyDetail:
        return PropertyDetail(title="", price=0, location="", description="",
                              images=[], source=self.source_name, url=url)
