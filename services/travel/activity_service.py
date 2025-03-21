import os
import requests
import logging
from typing import Optional

# Configure logger
logger = logging.getLogger(__name__)

class ActivityService:
    """Service for handling activity-related operations using the Google Places API."""

    def get_activities(self, destination: str, preferences: Optional[str] = None) -> str:
        """
        Get activity recommendations for a destination using the Google Places API.

        Args:
            destination: Destination city.
            preferences: User activity preferences (optional).

        Returns:
            A string summarizing activity recommendations.
        """
        logger.info(f"Getting activities in {destination} with preferences: {preferences}")
        google_api_key = os.getenv("GOOGLE_PLACES_API_KEY")
        if not google_api_key:
            logger.error("GOOGLE_PLACES_API_KEY not set in environment.")
            return "Error: Google Places API key is not configured."

        # Build the query. For example: "things to do in Paris" or include preferences.
        query = f"things to do in {destination}"
        if preferences:
            query += f" {preferences}"
        
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": query,
            "key": google_api_key,
            "type": "tourist_attraction"
        }
        try:
            response = requests.get(url, params=params)
            if response.status_code != 200:
                logger.error(f"Google Places API error: {response.status_code} {response.text}")
                return f"Error: Unable to retrieve activity data (HTTP {response.status_code})."

            data = response.json()
            results = data.get("results", [])
            if not results:
                return f"No activities found in {destination}."

            # Build a summary string of the top 5 activity results.
            activity_summaries = []
            for result in results[:5]:
                name = result.get("name", "Unknown")
                address = result.get("formatted_address", "No address provided")
                rating = result.get("rating", "No rating")
                summary = f"{name} (Rating: {rating}) - {address}"
                activity_summaries.append(summary)

            return " | ".join(activity_summaries)
        except Exception as e:
            logger.error(f"Exception in get_activities: {e}")
            return f"Error fetching activities: {e}"
