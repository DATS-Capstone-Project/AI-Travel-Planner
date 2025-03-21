# services/travel/hotel_service.py

import logging
import requests
from typing import Optional
from datetime import datetime
from config.settings import DEFAULT_BUDGET
import os

# Configure logger
logger = logging.getLogger(__name__)

class HotelService:
    """Service for handling hotel-related operations"""

    def get_hotels(self, destination: str, start_date: str, end_date: str, budget: Optional[int] = None) -> str:
        """
        Get hotel information for a trip using the Google Places Text Search API.

        Args:
            destination: Destination city.
            start_date: Check-in date in YYYY-MM-DD format.
            end_date: Check-out date in YYYY-MM-DD format.
            budget: Budget per night in USD (optional).

        Returns:
            A string summarizing hotel options.
        """
        if budget is None:
            budget = DEFAULT_BUDGET

        logger.info(f"Getting hotels in {destination} from {start_date} to {end_date} with budget ${budget}/night")

        # Retrieve your Google Places API key from environment
        google_api_key =  os.getenv("GOOGLE_PLACES_API_KEY")
        if not google_api_key:
            logger.error("GOOGLE_PLACES_API_KEY not set in environment.")
            return "Error: Google Places API key is not configured."

        # Construct a query; you might adjust this query if you want 4-star hotels, etc.
        query = f"hotels in {destination}"
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": query,
            "key": google_api_key,
            "type": "lodging"
        }
        try:
            response = requests.get(url, params=params)
            if response.status_code != 200:
                logger.error(f"Google Places API error: {response.status_code} {response.text}")
                return "Error: Unable to retrieve hotel data from Google Places."

            data = response.json()
            results = data.get("results", [])
            if not results:
                return f"No hotels found in {destination}."

            # Build a summary string of the first few hotel options.
            hotel_summaries = []
            for hotel in results[:5]:
                name = hotel.get("name", "Unknown")
                address = hotel.get("formatted_address", "No address provided")
                rating = hotel.get("rating", "No rating")
                price_level = hotel.get("price_level", "N/A")
                # Optionally, you might want to filter or map the price_level using the provided budget.
                summary = f"{name} (Rating: {rating}, Price Level: {price_level}) - {address}"
                hotel_summaries.append(summary)

            hotels_info = " | ".join(hotel_summaries)
            return f"Hotel options in {destination}: {hotels_info}"
        except Exception as e:
            logger.error(f"Exception in get_hotels: {e}")
            return f"Error retrieving hotels: {e}"

    def calculate_nightly_budget(self, total_budget: int, start_date: str, end_date: str) -> int:
        """
        Calculate per-night budget from total trip budget

        Args:
            total_budget: Total budget for the trip.
            start_date: Check-in date in YYYY-MM-DD format.
            end_date: Check-out date in YYYY-MM-DD format.

        Returns:
            Budget per night.
        """
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            nights = (end - start).days
            if nights <= 0:
                return DEFAULT_BUDGET
            accommodation_budget = total_budget * 0.6
            per_night = int(accommodation_budget / nights)
            return max(per_night, 50)
        except Exception as e:
            logger.error(f"Error calculating nightly budget: {e}")
            return DEFAULT_BUDGET
