import asyncio
import json
import logging

import httpx
from openai import OpenAI

from app.core.config import settings
from app.services.base import PropertyListing
from app.services.olx_service import OLXAgent
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
    def __init__(self):
        self.scraped_listings: list[PropertyListing] = []
        self.service_agents = [
            OLXAgent(),
            MamikostAgent(),
            PinhomeAgent(),
            LamudiAgent(),
            FacebookAgent(),
        ]

    async def search_listings(
        self,
        location: str,
        budget_min: int,
        budget_max: int,
        status_pernikahan: str = "lajang",
        limit_per_source: int = 3,
    ) -> list[PropertyListing]:
        property_type = "kontrakan" if status_pernikahan == "menikah" else "kost"

        async with httpx.AsyncClient() as client:
            tasks = [
                agent.search_and_analyze(
                    client, location, budget_min, budget_max, property_type, limit_per_source,
                )
                for agent in self.service_agents
            ]
            results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

        self.scraped_listings = []
        for result in results_per_source:
            if isinstance(result, list):
                self.scraped_listings.extend(result)

        logger.info(
            "Scraped %d listings from %d sources for %s in %s",
            len(self.scraped_listings),
            len(set(l.source for l in self.scraped_listings)),
            property_type,
            location,
        )

        return self.scraped_listings

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
        for listing in listings[:10]:
            products.append({
                "nama_tempat": listing.title,
                "tipe": listing.property_type or "Kost",
                "harga": f"Rp{listing.price:,}" if listing.price else "Harga nego",
                "lokasi": listing.location,
                "sumber": listing.source,
                "url": listing.url,
            })
        return products

    def _generate_llm_products(self, user_message: str, user_info: dict, language: str = "id") -> list[dict]:
        from app.controllers.orchestrator_controller import recommendationMessages

        details = {
            'message': user_message,
            'user_information': user_info,
        }
        llm_response = recommendationMessages(json.dumps(details), language)
        tempat_list = [t.strip() for t in llm_response.split(",") if t.strip()]

        products = []
        for tempat_name in tempat_list:
            products.append({
                "nama_tempat": tempat_name,
                "tipe": "Kost" if "kost" in tempat_name.lower() else "Kontrakan",
                "harga": "Sesuai budget",
                "lokasi": user_info.get("lokasi", ""),
            })
        return products

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

        await self.search_listings(
            location=location,
            budget_min=budget_min,
            budget_max=budget_max,
            status_pernikahan=status,
            limit_per_source=limit_per_source,
        )

        ranked = self.rank_listings(budget_min, budget_max)

        if ranked:
            details_json = self.format_for_llm(ranked, user_info)
            products = self.listings_to_products(ranked)
        else:
            products = self._generate_llm_products(user_message, user_info, language)
            details_json = json.dumps({
                "tempat_rekomendasi": [{"nama": p["nama_tempat"], "tipe": p["tipe"]} for p in products],
                "user_information": user_info,
            })

        check_result = self.generate_recommendation_text(details_json, language)

        return {
            "rc": "200",
            "messages": [line for line in check_result.splitlines() if line.strip()],
            "is_product": True,
            "product": products,
        }
