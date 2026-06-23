"""
Lamudi Agent — scrapes lamudi.co.id via Playwright.
Data: kost & hunian sewa.
URL pattern: /sewa/{province}/{city}/rumah/rumah-kosan/ untuk kost,
/sewa/{province}/{city}/rumah/ untuk kontrakan.
Listing link punya pola lamudi.co.id/.+/.+ tanpa query string.
"""
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.agents.base_agent import BasePropertyAgent
from app.agents._browser import fetch_page, clean_price, first_img, parse_specs
from app.services.base import PropertyListing, PropertyDetail

logger = logging.getLogger(__name__)

BASE_URL = "https://www.lamudi.co.id"

# Province mapping untuk URL Lamudi (provinsi/kota).
_LAMUDI_PROVINCE_MAP = {
    "jakarta": "jakarta",
    "jakarta-pusat": "jakarta",
    "jakarta-selatan": "jakarta",
    "jakarta-utara": "jakarta",
    "jakarta-barat": "jakarta",
    "jakarta-timur": "jakarta",
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


class LamudiAgent(BasePropertyAgent):
    source_name = "Lamudi"

    def _build_url(self, location: str, property_type: str) -> str:
        slug = location.strip().lower().replace(" ", "-")
        province = _LAMUDI_PROVINCE_MAP.get(slug)
        if property_type == "kost":
            if province:
                return f"{BASE_URL}/sewa/{province}/{slug}/rumah/rumah-kosan/"
            return f"{BASE_URL}/sewa/rumah/rumah-kosan/?location={slug}"
        if province:
            return f"{BASE_URL}/sewa/{province}/{slug}/rumah/"
        return f"{BASE_URL}/sewa/rumah/{slug}/"

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
            html = await fetch_page(url, wait_selector="[class*='title'], h2, h3")
            if not html:
                return []
            return self._parse(html, limit)
        except Exception as e:
            logger.warning("[Lamudi] search failed: %s", e)
            return []

    # URL segments that indicate non-listing pages (articles, guides, KPR, etc.)
    _JUNK_SEGMENTS = (
        "/beli/", "/cari/", "/journal/", "/jurnal/", "/kpr/", "/panduan/",
        "/pedoman/", "/blog/", "/artikel/", "/tips/", "/bantuan/", "/tentang/",
        "/kebijakan/", "/syarat/", "/career/", "/karir/", "/hubungi/", "/partner/",
        "/faq/", "/disclaimer/",
    )
    # URL segments that indicate actual rental listings
    _RENTAL_SEGMENTS = ("/sewa/", "/disewakan/")

    def _parse(self, html: str, limit: int) -> list[PropertyListing]:
        soup = BeautifulSoup(html, "html.parser")
        results = []
        seen = set()

        for snippet in soup.find_all("div", class_=re.compile(r"\bsnippet\b")):
            if len(results) >= limit:
                break

            title_el = snippet.find("span", class_=re.compile(r"snippet__content__title")) or snippet.find("span", itemprop="name")
            if not title_el:
                continue
            title = title_el.get("content", "").strip() or title_el.get_text(strip=True)
            if not title or len(title) < 8:
                continue
            if any(k in title.lower() for k in ["featured", "rekan lamudi", "partner"]):
                continue

            href_a = snippet.find("a", href=re.compile(r"^/(sewa|properti)/"))
            if not href_a:
                continue
            href = href_a.get("href", "")
            if href in seen or not href:
                continue
            href_lower = href.lower()
            if any(x in href_lower for x in self._JUNK_SEGMENTS):
                continue
            if not any(x in href_lower for x in self._RENTAL_SEGMENTS):
                continue
            seen.add(href)

            price_str = snippet.find("span", class_=re.compile(r"snippet__content__price"))
            price_text = price_str.get_text(strip=True) if price_str else ""
            if not price_text:
                price_text = snippet.find(string=re.compile(r"Rp\s*[\d]", re.I))
            price = clean_price(str(price_text)) if price_text else 0

            image = first_img(snippet)

            results.append(PropertyListing(
                title=title[:120], price=price, location="", property_type="",
                source=self.source_name, url=urljoin(BASE_URL, href),
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
            desc_el = soup.select_one("[class*='desc'], [class*='Description'], [itemprop='description']")
            description = desc_el.get_text(separator="\n", strip=True)[:1500] if desc_el else ""
            specs = parse_specs(soup)
            images = [img["src"] for img in soup.select("img[src]")
                      if img.get("src", "").startswith("http")][:8]
            return PropertyDetail(
                title=title, price=price, location="", description=description,
                images=images, source=self.source_name, url=url, **specs,
            )
        except Exception as e:
            logger.warning("[Lamudi] get_detail failed: %s", e)
            return self._empty(url)

    def _empty(self, url: str) -> PropertyDetail:
        return PropertyDetail(title="", price=0, location="", description="",
                              images=[], source=self.source_name, url=url)
