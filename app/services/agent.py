import asyncio
import json
import logging
import re

import httpx
from openai import OpenAI

from app.core.config import settings, prompts
from app.services.base import PropertyListing, PropertyDetail
from app.agents.rumah123_agent import Rumah123Agent
from app.agents.mamikost_agent import MamikostAgent
from app.agents.pinhome_agent import PinhomeAgent
from app.agents.lamudi_agent import LamudiAgent
from app.agents.ninetynineco_agent import NinetyNineCoAgent

logger = logging.getLogger(__name__)

llm_client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.LLM_URL,
)


_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\u2600-\u26FF"          # miscellaneous symbols
    "\u2700-\u27BF"          # dingbats
    "\u2300-\u23FF"          # miscellaneous technical
    "\u2B50-\u2B55"          # stars, etc.
    "\uFE00-\uFE0F"          # variation selectors
    "\U0001F3FB-\U0001F3FF" # skin tone modifiers
    "]+",
    flags=re.UNICODE,
)


def sanitize_text(text: str | None) -> str:
    """Strip emojis and other decorative Unicode characters, then clean whitespace."""
    if not text:
        return ""
    text = _EMOJI_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


class HousingAgent:
    # Sources that are expected to provide real URLs and images
    RELIABLE_SOURCES = {"Rumah123", "Mamikost", "Pinhome", "Lamudi", "99.co"}

    def __init__(self):
        self.scraped_listings: list[PropertyListing] = []
        self.service_agents = [
            Rumah123Agent(),
            MamikostAgent(),
            PinhomeAgent(),
            LamudiAgent(),
            NinetyNineCoAgent(),
        ]

    # URL/title patterns that indicate articles, guides, and other non-listings
    _JUNK_URL_SEGMENTS = (
        "/journal/", "/jurnal/", "/kpr/", "/panduan/", "/pedoman/", "/blog/",
        "/artikel/", "/tips/", "/bantuan/", "/tentang/", "/kebijakan/", "/syarat/",
        "/career/", "/karir/", "/hubungi/", "/partner/", "/faq/", "/disclaimer/",
    )
    _JUNK_TITLE_KEYWORDS = (
        "simulasi", "kpr", "panduan", "pedoman", "jurnal", "journal", "blog",
        "artikel", "berita", "tips", "cara", "syarat", "tutorial", "kuis",
        "faq", "bantuan", "tentang", "kebijakan", "ketentuan", "disclaimer",
        "partner", "karir", "career", "hubungi", "dijual",
    )

    def _is_valid_listing(
        self,
        listing: PropertyListing,
        location: str,
        budget_min: int = 0,
        budget_max: int = 0,
        property_type: str = "kost",
    ) -> bool:
        """Filter out junk/non-property listings and enforce budget/tenure/type."""
        title = (listing.title or "").lower().strip()
        url = (listing.url or "").lower().strip()
        if not title or len(title) < 5:
            return False

        # Reject non-listing pages (guides, articles, KPR, etc.)
        if any(k in title for k in self._JUNK_TITLE_KEYWORDS):
            return False
        if any(k in url for k in self._JUNK_URL_SEGMENTS):
            return False

        if property_type == "kontrakan":
            # Kontrakan searches should not return kost/kosan/boarding rooms
            if any(k in title for k in ["kost", "kos", "kosan", "kost-kostan", "kost putri", "kost cowok", "kos putri", "kos cowok"]):
                return False

        # Property-related keywords any valid title should contain
        property_keywords = [
            "kost", "kos", "kontrakan", "rumah", "apartemen",
            "apartment", "sewa", "kamar", "disewakan", "cluster",
            "perumahan", "ruko", "villa", "mewah", "asri", "nyaman", "strategis",
        ]
        has_property_keyword = any(k in title for k in property_keywords)

        is_reliable = listing.source in self.RELIABLE_SOURCES

        # Reject sale listings when we are looking for rentals (kost/kontrakan/apartemen)
        if "dijual" in title or " for sale" in title or "jual rumah" in title:
            return False

        if not listing.url and not has_property_keyword:
            # Fake LLM-fallback listings usually have no URL and no property keyword
            return False

        if not is_reliable and not has_property_keyword:
            # Facebook/other unreliable sources must have a property keyword
            return False

        if not is_reliable and (not listing.url or not listing.image_url):
            # Unreliable sources must provide both URL and image
            return False

        if listing.price < 0:
            return False

        # Enforce price range against the requested budget
        if budget_max > 0 and listing.price > 0:
            yearly_keywords = ["tahun", "tahunan", "per tahun", "yearly", "tahunan"]
            is_yearly = any(k in title for k in yearly_keywords)
            if is_yearly:
                max_allowed = budget_max * 12
            else:
                # Monthly or unknown: allow small tolerance above monthly budget
                max_allowed = budget_max * 1.5
            if listing.price > max_allowed:
                return False
            if listing.price < budget_min * 0.5:
                return False

        return True

    async def _expand_location(
        self,
        location: str,
        property_type: str,
        language: str = "id",
    ) -> list[str]:
        """Use LLM to expand broad regions (e.g., Jabodetabek) into specific cities."""
        prompt = prompts.format(language, "expand_location",
                                property_type=property_type, location=location)
        try:
            response = llm_client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": prompts.get(language, "system")},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=100,
                stream=False,
            )
            text = response.choices[0].message.content.strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            locations = json.loads(text)
            if isinstance(locations, list) and locations:
                locations = [str(loc).strip() for loc in locations if loc]
                # If the LLM returned a broader location (e.g. "Jakarta Pusat" -> "Jakarta"),
                # keep the original specific location as a safety net.
                original_lower = location.lower().strip()
                if not any(original_lower in loc.lower() or loc.lower() in original_lower for loc in locations):
                    locations.insert(0, location)
                return locations
        except Exception as e:
            logger.warning("_expand_location failed: %s", e)
        return [location]

    async def _search_single_location(
        self,
        location: str,
        budget_min: int,
        budget_max: int,
        status_pernikahan: str,
        limit_per_source: int,
    ) -> tuple[list[PropertyListing], dict[str, int]]:
        property_type = "kontrakan" if status_pernikahan == "menikah" else "kost"

        applicable_agents = [agent for agent in self.service_agents if agent.supports(property_type)]
        tasks = [
            agent.search(location, budget_min, budget_max, property_type, limit_per_source)
            for agent in applicable_agents
        ]
        results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

        listings: list[PropertyListing] = []
        source_counts: dict[str, int] = {
            agent.source_name: 0 for agent in self.service_agents
        }
        for idx, result in enumerate(results_per_source):
            agent_name = applicable_agents[idx].source_name
            if isinstance(result, list):
                valid = [l for l in result if self._is_valid_listing(l, location, budget_min, budget_max, property_type)]
                source_counts[agent_name] = len(valid)
                logger.info(
                    "[%-20s] loc=%s raw=%d valid=%d",
                    agent_name,
                    location,
                    len(result),
                    len(valid),
                )
                for listing in valid:
                    # Tag the listing with the requested property type so the response
                    # shows the correct type (Kost/Kontrakan) instead of defaulting to Kost.
                    listing.property_type = property_type.title()
                    logger.info(
                        "[%-20s] listing: title=%s price=%s source=%s url=%s image=%s",
                        agent_name,
                        listing.title,
                        listing.price,
                        listing.source,
                        listing.url,
                        listing.image_url,
                    )
                listings.extend(valid)
            elif isinstance(result, Exception):
                logger.warning("[%-20s] loc=%s error: %s", agent_name, location, result)
                source_counts[agent_name] = 0

        return listings, source_counts

    def rank_listings(self, budget_min: int, budget_max: int) -> list[PropertyListing]:
        mid_budget = (budget_min + budget_max) / 2
        scored: list[tuple[float, PropertyListing]] = []

        for listing in self.scraped_listings:
            score = 0.0

            if listing.price > 0:
                distance = abs(listing.price - mid_budget) / max(mid_budget, 1)
                score += max(0, 30 - distance * 30)

            if listing.title and len(listing.title) > 5:
                score += 10

            if listing.description:
                score += min(len(listing.description) / 50, 10)

            if listing.image_url:
                score += 5

            if listing.bedrooms > 0:
                score += 5

            scored.append((score, listing))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored]

    def format_for_llm(self, listings: list[PropertyListing], user_info: dict) -> str:
        if not listings:
            return json.dumps({
                "tempat_rekomendasi": [],
                "user_information": user_info,
                "note": "Tidak ada hasil scraping. Gunakan LLM untuk generate rekomendasi.",
            })

        formatted = []
        for i, listing in enumerate(listings[:10], 1):
            formatted.append({
                "nama": sanitize_text(listing.title),
                "tipe": listing.property_type or "kost",
                "harga": listing.price,
                "lokasi": sanitize_text(listing.location),
                "sumber": listing.source,
                "url": listing.url,
            })

        return json.dumps({
            "tempat_rekomendasi": formatted,
            "user_information": user_info,
        })

    def generate_recommendation_text(self, details_json: str, language: str = "id") -> str:
        lang = (language or "id").lower()
        messages = [
            {"role": "system", "content": prompts.get(lang, "system")},
            {"role": "system", "content": prompts.get(lang, "filter")},
            {"role": "system", "content": prompts.get(lang, "check_recommendation")},
            {"role": "user", "content": details_json},
        ]

        try:
            stream = llm_client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=0.5,
                max_tokens=500,
                top_p=0.7,
                stream=True,
            )
            response_text = "".join(
                chunk.choices[0].delta.content
                for chunk in stream
                if chunk.choices[0].delta.content
            )
            return sanitize_text(response_text)
        except Exception as e:
            logger.error("LLM recommendation generation failed: %s", e)
            return sanitize_text(self._fallback_text(listings_json=details_json, language=language))

    def _fallback_text(self, listings_json: str, language: str = "id") -> str:
        lang = (language or "id").lower()
        try:
            data = json.loads(listings_json)
            places = data.get("tempat_rekomendasi", [])
            if not places:
                if lang == "en":
                    return "Sorry, there are no recommendations available at the moment."
                return "Maaf, belum ada rekomendasi yang tersedia saat ini."

            if lang == "en":
                lines = ["Here are accommodation recommendations that suit you:"]
            else:
                lines = ["Berikut rekomendasi tempat tinggal yang cocok untukmu:"]
            for p in places[:5]:
                price_str = f"Rp{p['harga']:,}" if p.get("harga") else "Harga nego"
                lines.append(
                    f"- {p['nama']} ({p['tipe']}) - {price_str} "
                    f"di {p.get('lokasi', '')} via {p.get('sumber', '')}"
                )
            return "\n".join(lines)
        except Exception:
            if lang == "en":
                return "Here are some accommodation recommendations that might suit you."
            return "Berikut beberapa rekomendasi tempat tinggal yang mungkin cocok untukmu."

    def listings_to_products(self, listings: list[PropertyListing]) -> list[dict]:
        products = []
        yearly_keywords = ["tahun", "tahunan", "per tahun", "yearly", "tahunan"]
        for listing in listings[:10]:
            title_lower = (listing.title or "").lower()
            is_yearly = any(k in title_lower for k in yearly_keywords)
            if is_yearly and listing.price > 1000000:
                monthly_price = listing.price // 12
                price_label = f"Rp{monthly_price:,}/bulan (Rp{listing.price:,}/tahun)"
            else:
                price_label = f"Rp{listing.price:,}" if listing.price else "Harga nego"
            products.append({
                "nama_tempat": sanitize_text(listing.title),
                "tipe": listing.property_type or "Kost",
                "harga": price_label,
                "lokasi": listing.location,
                "sumber": listing.source,
                "url": listing.url,
                "image": listing.image_url,
            })
        return products

    async def get_detail(self, url: str, source: str) -> PropertyDetail:
        for agent in self.service_agents:
            if agent.source_name == source:
                detail = await agent.get_detail(url)
                if detail.title or detail.images:
                    detail.title = sanitize_text(detail.title)
                    detail.location = sanitize_text(detail.location)
                    detail.description = sanitize_text(detail.description)
                    return detail
        return PropertyDetail(
            title="",
            price=0,
            location="",
            description="",
            images=[],
            source=source,
            url=url,
        )

    def _generate_text_recommendation(
        self,
        user_message: str,
        user_info: dict,
        language: str = "id",
    ) -> str:
        lang = (language or "id").lower()
        prompt = prompts.format(lang, "text_recommendation",
                                user_info=json.dumps(user_info, ensure_ascii=False))
        messages = [
            {"role": "system", "content": prompts.get(lang, "system")},
            {"role": "system", "content": prompts.get(lang, "filter")},
            {"role": "user", "content": prompt},
        ]

        try:
            stream = llm_client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=0.5,
                max_tokens=500,
                top_p=0.7,
                stream=True,
            )
            return sanitize_text("".join(
                chunk.choices[0].delta.content
                for chunk in stream
                if chunk.choices[0].delta.content
            ))
        except Exception as e:
            logger.error("LLM text recommendation failed: %s", e)
            return sanitize_text(self._fallback_text(json.dumps({"tempat_rekomendasi": [], "user_information": user_info}), language))

    async def run(
        self,
        user_message: str,
        user_info: dict,
        language: str = "id",
        limit_per_source: int = 3,
    ) -> dict:
        location = user_info.get("lokasi", "Jakarta")
        budget_min = user_info.get("budget_min", 500000)
        budget_max = user_info.get("budget_max", 3000000)
        status = user_info.get("status_pernikahan", "lajang")
        property_type = "kontrakan" if status == "menikah" else "kost"

        locations = await self._expand_location(location, property_type, language)
        logger.info("[EXPAND] %s -> %s", location, locations)

        # For broad regions, fetch more results per source to ensure good coverage
        effective_limit = limit_per_source
        if len(locations) > 1:
            effective_limit = max(limit_per_source, 5)

        # Run one search per expanded location in parallel
        search_tasks = [
            self._search_single_location(
                loc, budget_min, budget_max, status, effective_limit,
            )
            for loc in locations
        ]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        all_listings: list[PropertyListing] = []
        source_counts: dict[str, int] = {}
        for result in search_results:
            if isinstance(result, Exception):
                logger.warning("Search location failed: %s", result)
                continue
            listings, counts = result
            all_listings.extend(listings)
            for source, count in counts.items():
                source_counts[source] = source_counts.get(source, 0) + count

        # Deduplicate by URL
        seen_urls = set()
        deduped: list[PropertyListing] = []
        for listing in all_listings:
            if listing.url and listing.url in seen_urls:
                continue
            if listing.url:
                seen_urls.add(listing.url)
            deduped.append(listing)

        self.scraped_listings = deduped

        logger.info(
            "[TOTAL] %d listings across %d locations, %d sources",
            len(self.scraped_listings),
            len(locations),
            len(set(l.source for l in self.scraped_listings)),
        )

        ranked = self.rank_listings(budget_min, budget_max)

        if ranked:
            details_json = self.format_for_llm(ranked, user_info)
            products = self.listings_to_products(ranked)
            check_result = self.generate_recommendation_text(details_json, language)
            messages = [line for line in check_result.splitlines() if line.strip()]
            if len(locations) > 1:
                location_str = ", ".join(locations)
                if language.lower() == "en":
                    summary = f"Searching across {len(locations)} areas: {location_str}. Found {len(products)} properties within your budget."
                else:
                    summary = f"Mencari di {len(locations)} wilayah: {location_str}. Ditemukan {len(products)} properti dalam budget Anda."
                messages.insert(0, summary)
            response = {
                "rc": "200",
                "messages": messages,
                "is_product": True,
                "product": products,
                "source_counts": source_counts,
            }
            logger.info("[RESPONSE] is_product=True products=%d", len(products))
            return response

        text_response = self._generate_text_recommendation(user_message, user_info, language)
        response = {
            "rc": "200",
            "messages": [line for line in text_response.splitlines() if line.strip()],
            "is_product": False,
            "product": [],
            "source_counts": source_counts,
        }
        logger.info("[RESPONSE] is_product=False products=0 (fallback text)")
        return response
