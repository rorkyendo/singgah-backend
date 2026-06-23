"""
Shared browser utilities untuk semua property agents.

Menggunakan Selenium + ChromeDriver. Selenium menjalankan chromedriver via
subprocess.Popen secara langsung (tidak melalui asyncio), sehingga tidak
terkena NotImplementedError pada Windows seperti Playwright.
"""
import asyncio
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

# Thread pool — maks 3 halaman berjalan paralel
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="selenium")

# Tiap worker thread punya Selenium WebDriver instance sendiri.
_thread_local = threading.local()


def _build_chrome_options() -> Options:
    opts = Options()
    chrome_bin = os.getenv("CHROME_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    opts.add_argument("--lang=id-ID")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return opts


def _get_thread_driver() -> webdriver.Chrome:
    """Buat atau kembalikan Selenium WebDriver untuk thread ini."""
    driver = getattr(_thread_local, "driver", None)
    if driver is None:
        driver = webdriver.Chrome(options=_build_chrome_options())
        driver.execute_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)
        logger.info("Selenium Chrome driver started (thread=%s)", threading.current_thread().name)
        _thread_local.driver = driver
    return driver


def _fetch_page_sync(url: str, wait_selector: Optional[str] = None, timeout: int = 20000, sleep: float = 0.0) -> Optional[str]:
    """Synchronous Selenium fetch — dijalankan di worker thread."""
    try:
        driver = _get_thread_driver()
        driver.get(url)
        if wait_selector:
            try:
                WebDriverWait(driver, min(timeout / 1000, 10)).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                )
            except Exception:
                pass
        else:
            time.sleep(2.5)
        if sleep > 0:
            time.sleep(sleep)
        return driver.page_source
    except Exception as e:
        logger.warning("fetch_page failed for %s: %s", url, e)
        return None


async def fetch_page(url: str, wait_selector: Optional[str] = None, timeout: int = 20000, sleep: float = 0.0) -> Optional[str]:
    """Async wrapper — offload Selenium ke thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: _fetch_page_sync(url, wait_selector, timeout, sleep),
    )


def _close_thread_driver():
    """Tutup driver di thread ini."""
    driver = getattr(_thread_local, "driver", None)
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
        _thread_local.driver = None


async def close_browser():
    """Dipanggil saat FastAPI shutdown."""
    loop = asyncio.get_event_loop()
    futures = [loop.run_in_executor(_executor, _close_thread_driver) for _ in range(3)]
    await asyncio.gather(*futures, return_exceptions=True)
    _executor.shutdown(wait=False)
    logger.info("Selenium Chrome drivers stopped")


# ---------------------------------------------------------------------------
# Parsing helpers — dipakai oleh semua agent
# ---------------------------------------------------------------------------

def clean_price(text: str) -> int:
    """Parse teks harga Indonesia ke integer.
    Handles: Rp 1,9 Juta / Rp 1.500.000 / Rp 850 Ribu / Rp2jt
    """
    if not text:
        return 0
    text = str(text).strip()
    m = re.search(r"Rp\s*([\d]+(?:[.,][\d]+)?)\s*(Juta|Miliar|Ribu|juta|miliar|ribu|jt|rb|k)?", text, re.I)
    if not m:
        m2 = re.search(r"(\d+(?:[.,]\d+)?)\s*(juta|miliar|ribu|jt|rb|k)?", text.lower())
        if not m2:
            return 0
        raw = m2.group(1).replace(",", ".").replace(".", "")
        try:
            val = float(raw)
        except ValueError:
            return 0
        unit = (m2.group(2) or "").lower()
        if unit in ("jt", "juta"):
            val *= 1_000_000
        elif unit in ("rb", "ribu", "k"):
            val *= 1_000
        return int(val)

    raw = m.group(1)
    unit = (m.group(2) or "").lower()

    if re.match(r"^\d+,\d{1,2}$", raw):
        val = float(raw.replace(",", "."))
    else:
        val = float(raw.replace(".", "").replace(",", ""))

    if unit in ("jt", "juta"):
        val *= 1_000_000
    elif unit in ("rb", "ribu", "k"):
        val *= 1_000
    elif unit == "miliar":
        val *= 1_000_000_000
    return int(val)


def first_img(tag) -> str:
    """Ambil URL gambar pertama dari tag."""
    img = tag.find("img") if tag else None
    if not img:
        return ""
    return img.get("src") or img.get("data-src") or img.get("data-original") or ""


def parse_specs(soup) -> dict:
    """Ekstrak bedrooms, bathrooms, luas, dan fasilitas dari halaman detail."""
    specs = {"bedrooms": 0, "bathrooms": 0, "land_area": 0, "building_area": 0, "facilities": []}
    for el in soup.find_all(["li", "span", "div", "td"]):
        text = el.get_text(" ", strip=True).lower()
        if len(text) > 100:
            continue
        if any(k in text for k in ["kamar tidur", "bedroom", "kt"]):
            m = re.search(r"(\d+)", text)
            if m and not specs["bedrooms"]:
                specs["bedrooms"] = int(m.group(1))
        elif any(k in text for k in ["kamar mandi", "bathroom", "km"]):
            m = re.search(r"(\d+)", text)
            if m and not specs["bathrooms"]:
                specs["bathrooms"] = int(m.group(1))
        elif any(k in text for k in ["luas bangunan", "building area", "lb"]):
            m = re.search(r"(\d+)", text)
            if m and not specs["building_area"]:
                specs["building_area"] = int(m.group(1))
        elif any(k in text for k in ["luas tanah", "land area", "lt"]):
            m = re.search(r"(\d+)", text)
            if m and not specs["land_area"]:
                specs["land_area"] = int(m.group(1))

    for el in soup.select("[class*='facilit'], [class*='amenity'], [class*='feature']"):
        txt = el.get_text(strip=True)
        if txt and 3 < len(txt) < 40:
            specs["facilities"].append(txt)

    specs["facilities"] = list(dict.fromkeys(specs["facilities"]))[:10]
    return specs
