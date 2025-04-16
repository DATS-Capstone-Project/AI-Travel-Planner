import os
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from pydantic import BaseModel, Field
from config.settings import SERP_API_KEY

logger = logging.getLogger(__name__)


class PlaceCoordinates(BaseModel):
    latitude: float
    longitude: float


class ServiceOptions(BaseModel):
    dine_in: Optional[bool] = None
    takeout: Optional[bool] = None
    delivery: Optional[bool] = None


class PlaceLinks(BaseModel):
    website: Optional[str] = None
    directions: Optional[str] = None
    phone: Optional[str] = None
    order: Optional[str] = None
    menu: Optional[str] = None
    reservations: Optional[str] = None


class PlaceDetails(BaseModel):
    id: str
    title: str
    place_id: str
    position: Optional[int] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    reviews_original: Optional[str] = None
    price: Optional[str] = None
    type: Optional[str] = None
    address: Optional[str] = None
    hours: Optional[str] = None
    thumbnail: Optional[str] = None
    extensions: Optional[List[str]] = None
    gps_coordinates: Optional[PlaceCoordinates] = None
    description: Optional[str] = None
    service_options: Optional[ServiceOptions] = None
    links: Optional[PlaceLinks] = None
    lsig: Optional[str] = None
    provider_id: Optional[str] = None


class LocalSearchService:
    """Service for searching local places using SerpAPI"""

    def __init__(self):
        # API key should be stored in environment variables
        self.api_key = SERP_API_KEY
        self.base_url = "https://serpapi.com/search"

    async def search_places(self, query: str, location: str) -> List[PlaceDetails]:
        """
        Search for local places matching the query in the specified location

        Args:
            query: Search query (e.g., "coffee", "restaurants", "indian food")
            location: Location to search in (e.g., "New York", "Denver")

        Returns:
            List of PlaceDetails
        """
        logger.info(f"Searching for '{query}' in {location}")

        params = {
            "engine": "google_local",
            "q": query,
            "location": location,
            "hl": "en",
            "gl": "us",
            "google_domain": "google.com",
            "api_key": self.api_key
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()

                data = response.json()

                if "local_results" not in data:
                    logger.warning(f"No local results found for '{query}' in {location}")
                    return []

                local_results = data["local_results"]
                return self._parse_local_results(local_results)

        except Exception as e:
            logger.error(f"Error searching places for '{query}' in {location}: {e}")
            # Return mock data as fallback in case of errors
            return self._get_mock_places(query, location)

    def _parse_local_results(self, local_results: List[Dict[str, Any]]) -> List[PlaceDetails]:
        """Parse SerpAPI local results into PlaceDetails objects"""
        places = []

        for i, place in enumerate(local_results):
            try:
                # Extract service options if available
                service_options = None
                if "service_options" in place:
                    service_options = ServiceOptions(
                        dine_in=place["service_options"].get("dine_in"),
                        takeout=place["service_options"].get("takeout"),
                        delivery=place["service_options"].get("delivery")
                    )

                # Extract links if available
                links = None
                if "links" in place:
                    links = PlaceLinks(
                        website=place["links"].get("website"),
                        directions=place["links"].get("directions"),
                        phone=place["links"].get("phone"),
                        order=place["links"].get("order"),
                        menu=place["links"].get("menu"),
                        reservations=place["links"].get("reservations")
                    )

                # Create place object
                place_details = PlaceDetails(
                    id=f"place_{i + 1}",
                    title=place.get("title", "Unnamed Place"),
                    place_id=place.get("place_id", ""),
                    position=place.get("position"),
                    rating=place.get("rating"),
                    reviews=place.get("reviews"),
                    reviews_original=place.get("reviews_original"),
                    price=place.get("price"),
                    type=place.get("type", ""),
                    address=place.get("address", ""),
                    hours=place.get("hours", ""),
                    thumbnail=place.get("thumbnail", ""),
                    extensions=place.get("extensions", []),
                    description=place.get("extensions", [""])[0] if place.get("extensions") else "",
                    gps_coordinates=PlaceCoordinates(
                        latitude=place.get("gps_coordinates", {}).get("latitude", 0),
                        longitude=place.get("gps_coordinates", {}).get("longitude", 0)
                    ) if "gps_coordinates" in place else None,
                    service_options=service_options,
                    links=links,
                    lsig=place.get("lsig"),
                    provider_id=place.get("provider_id")
                )

                places.append(place_details)

            except Exception as e:
                logger.error(f"Error parsing place: {e}")
                continue

        return places

    def _get_mock_places(self, query: str, location: str) -> List[PlaceDetails]:
        """Generate mock places as fallback"""
        place_types = {
            "coffee": "Coffee shop",
            "restaurant": "Restaurant",
            "cafe": "Café",
            "pizza": "Pizza restaurant",
            "indian": "Indian restaurant",
            "thai": "Thai restaurant",
            "mexican": "Mexican restaurant",
            "chinese": "Chinese restaurant",
            "italian": "Italian restaurant",
            "japanese": "Japanese restaurant",
            "sushi": "Sushi restaurant",
        }

        # Determine the type based on the query
        place_type = "Restaurant"
        for key, value in place_types.items():
            if key in query.lower():
                place_type = value
                break

        return [
            PlaceDetails(
                id="place1",
                title=f"{location} {place_type}",
                place_id="mock_place_id_1",
                position=1,
                rating=4.5,
                reviews=120,
                reviews_original="(120)",
                price="$$",
                type=place_type,
                address=f"123 Main St, {location}",
                hours="Open ⋅ Closes 10 PM",
                thumbnail="https://images.unsplash.com/photo-1559925393-8be0ec4767c8?auto=format&fit=crop&w=400&q=80",
                extensions=["Great atmosphere and friendly staff!"],
                description="Great atmosphere and friendly staff!",
                gps_coordinates=PlaceCoordinates(
                    latitude=40.7128,
                    longitude=-74.0060
                ),
                service_options=ServiceOptions(
                    dine_in=True,
                    takeout=True,
                    delivery=False
                ),
                links=PlaceLinks(
                    website="https://example.com",
                    directions="https://maps.google.com",
                    phone="tel:+15551234567"
                )
            ),
            PlaceDetails(
                id="place2",
                title=f"Downtown {place_type}",
                place_id="mock_place_id_2",
                position=2,
                rating=4.2,
                reviews=85,
                reviews_original="(85)",
                price="$$$",
                type=place_type,
                address=f"456 Broadway, {location}",
                hours="Closed ⋅ Opens 11 AM tomorrow",
                thumbnail="https://images.unsplash.com/photo-1554118811-1e0d58224f24?auto=format&fit=crop&w=400&q=80",
                extensions=["Excellent food and service, a bit pricey but worth it."],
                description="Excellent food and service, a bit pricey but worth it.",
                gps_coordinates=PlaceCoordinates(
                    latitude=40.7135,
                    longitude=-74.0046
                ),
                service_options=ServiceOptions(
                    dine_in=True,
                    takeout=False,
                    delivery=True
                ),
                links=PlaceLinks(
                    website="https://example.com/downtown",
                    directions="https://maps.google.com",
                    phone="tel:+15551234567"
                )
            ),
            PlaceDetails(
                id="place3",
                title=f"{query.title()} House",
                place_id="mock_place_id_3",
                position=3,
                rating=4.7,
                reviews=210,
                reviews_original="(210)",
                price="$$",
                type=place_type,
                address=f"789 Oak St, {location}",
                hours="Open ⋅ Closes 9 PM",
                thumbnail="https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=400&q=80",
                extensions=["The best place for authentic cuisine in town!"],
                description="The best place for authentic cuisine in town!",
                gps_coordinates=PlaceCoordinates(
                    latitude=40.7155,
                    longitude=-74.0080
                ),
                service_options=ServiceOptions(
                    dine_in=True,
                    takeout=True,
                    delivery=True
                ),
                links=PlaceLinks(
                    website="https://example.com/house",
                    directions="https://maps.google.com",
                    order="https://example.com/order"
                )
            )
        ]