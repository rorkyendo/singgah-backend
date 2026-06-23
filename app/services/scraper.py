import asyncio

import httpx

from app.services.base import BaseScraper, PropertyListing
from app.services.rumah123_service import Rumah123Scraper
from app.services.mamikost_service import MamikostScraper
from app.services.pinhome_service import PinhomeScraper
from app.services.lamudi_service import LamudiScraper
from app.services.facebook_service import FacebookMarketplaceScraper


async def run_all_scrapers(
    location: str,
    budget_min: int,
    budget_max: int,
    property_type: str = "kost",
    limit_per_source: int = 3,
) -> list[PropertyListing]:
    scrapers: list[BaseScraper] = [
        Rumah123Scraper(),
        MamikostScraper(),
        PinhomeScraper(),
        LamudiScraper(),
        FacebookMarketplaceScraper(),
    ]

    async with httpx.AsyncClient() as client:
        tasks = [
            scraper.search(client, location, budget_min, budget_max, property_type, limit_per_source)
            for scraper in scrapers
        ]
        results_per_source = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[PropertyListing] = []
    for result in results_per_source:
        if isinstance(result, list):
            all_results.extend(result)

    all_results.sort(key=lambda x: x.price if x.price > 0 else float("inf"))
    return all_results
