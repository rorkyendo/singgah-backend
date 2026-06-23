import asyncio
import json
import logging

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import PropertyListing, PropertyDetail
from app.services.rumah123_service import Rumah123Agent
from app.services.mamikost_service import MamikostAgent
from app.services.pinhome_service import PinhomeAgent
from app.services.lamudi_service import LamudiAgent
from app.services.facebook_service import FacebookAgent

logger = logging.getLogger(__name__)

llm_client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.LLM_URL,
)


class HousingAgent:
    # Sources that are expected to provide real URLs and images
    RELIABLE_SOURCES = {"Rumah123", "Mamikost", "Pinhome", "Lamudi"}

    def __init__(self):
        self.scraped_listings: list[PropertyListing] = []
        self.service_agents = [
            Rumah123Agent(),
            MamikostAgent(),
            PinhomeAgent(),
            LamudiAgent(),
            FacebookAgent(),
        ]

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
        if not title or len(title) < 5:
            return False

        if property_type == "kontrakan":
            # Kontrakan searches should not return kost/kosan/boarding rooms
            if any(k in title for k in ["kost", "kosan", "kost-kostan", "kost putri", "kost cowok"]):
                return False

        # Property-related keywords any valid title should contain
        property_keywords = [
            "kost", "kos", "kontrakan", "kontrakan", "rumah", "apartemen",
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
        prompt = (
            f"User sedang mencari {property_type} di wilayah '{location}'. "
            "Jika lokasi tersebut adalah wilayah luas/metropolitan (misal Jabodetabek, Jabotabek, Greater Jakarta), "
            "kembalikan daftar kota/kabupaten spesifik yang termasuk dalam wilayah tersebut sebagai JSON array string. "
            f"Jika sudah spesifik, kembalikan [\"{location}\"]. "
            "Contoh: Jabodetabek -> [\"Jakarta\", \"Bogor\", \"Depok\", \"Tangerang\", \"Bekasi\"]. "
            "Kembalikan hanya JSON array string, tanpa penjelasan."
        )
        if language.lower() == "en":
            prompt = (
                f"User is searching for {property_type} in area '{location}'. "
                "If the location is a broad metropolitan region (e.g., Jabodetabek, Greater Jakarta), "
                "return a JSON array of specific cities/districts within that region. "
                f"If already specific, return [\"{location}\"]. "
                "Example: Jabodetabek -> [\"Jakarta\", \"Bogor\", \"Depok\", \"Tangerang\", \"Bekasi\"]. "
                "Return only a JSON array of strings, no explanation."
            )
        try:
            response = llm_client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": settings.SYSTEM_PROMPT},
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
                return [str(loc).strip() for loc in locations if loc]
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

        async with httpx.AsyncClient() as client:
            tasks = [
                agent.search_and_analyze(
                    client, location, budget_min, budget_max, property_type, limit_per_source,
                )
                for agent in self.service_agents
            ]
            results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

        listings: list[PropertyListing] = []
        source_counts: dict[str, int] = {}
        for idx, result in enumerate(results_per_source):
            agent_name = self.service_agents[idx].source_name
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
                "nama": listing.title,
                "tipe": listing.property_type or "kost",
                "harga": listing.price,
                "lokasi": listing.location,
                "sumber": listing.source,
                "url": listing.url,
            })

        return json.dumps({
            "tempat_rekomendasi": formatted,
            "user_information": user_info,
        })

    def _get_prompt(self, language: str, prompt_id: str) -> str:
        lang = (language or "id").lower()
        if lang == "en":
            return getattr(settings, f"{prompt_id}_EN", getattr(settings, prompt_id, ""))
        return getattr(settings, prompt_id, "")

    def generate_recommendation_text(self, details_json: str, language: str = "id") -> str:
        lang = (language or "id").lower()
        messages = [
            {"role": "system", "content": self._get_prompt(lang, "SYSTEM_PROMPT")},
            {"role": "system", "content": self._get_prompt(lang, "FILTER_PROMPT")},
            {"role": "system", "content": self._get_prompt(lang, "CHECK_RECOMENDATION_PROMPT")},
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
            return response_text
        except Exception as e:
            logger.error("LLM recommendation generation failed: %s", e)
            return self._fallback_text(listings_json=details_json, language=language)

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
                "nama_tempat": listing.title,
                "tipe": listing.property_type or "Kost",
                "harga": price_label,
                "lokasi": listing.location,
                "sumber": listing.source,
                "url": listing.url,
                "image": listing.image_url,
            })
        return products

    async def get_detail(self, url: str, source: str) -> PropertyDetail:
        async with httpx.AsyncClient() as client:
            for agent in self.service_agents:
                if agent.source_name == source:
                    detail = await agent.get_detail(client, url)
                    if detail.title or detail.images:
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
        prompt = (
            "Berikan 3 rekomendasi tempat tinggal (kost/kontrakan) yang cocok "
            f"berdasarkan data user: {json.dumps(user_info, ensure_ascii=False)}. "
            "Jawab dalam 2 paragraf: paragraf pertama ringkasan kebutuhan user, "
            "paragraf kedua rekomendasi tempat beserta alasannya. "
            "Jangan berikan format daftar/point. "
            "Gunakan bahasa Indonesia santai."
        ) if lang == "id" else (
            "Provide 3 accommodation recommendations (boarding house/rented house) that match "
            f"the user data: {json.dumps(user_info, ensure_ascii=False)}. "
            "Answer in 2 paragraphs: first paragraph summarizes user needs, "
            "second paragraph gives recommendations with reasons. "
            "Do not use bullet points. Keep it casual and friendly."
        )

        messages = [
            {"role": "system", "content": self._get_prompt(lang, "SYSTEM_PROMPT")},
            {"role": "system", "content": self._get_prompt(lang, "FILTER_PROMPT")},
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
            return "".join(
                chunk.choices[0].delta.content
                for chunk in stream
                if chunk.choices[0].delta.content
            )
        except Exception as e:
            logger.error("LLM text recommendation failed: %s", e)
            return self._fallback_text(json.dumps({"tempat_rekomendasi": [], "user_information": user_info}), language)

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
