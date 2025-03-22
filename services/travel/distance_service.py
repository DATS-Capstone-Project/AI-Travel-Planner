# services/travel/distance_service.py

import requests
import os
import logging
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

class DistanceService:
    BASE_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_PLACES_API_KEY")
        if not self.api_key:
            raise ValueError("Google Places API Key not set.")

    def check_proximity(self, hotels, activities, threshold_km=10):
        hotel_addresses = [hotel.split(" - ")[-1] for hotel in hotels]
        activity_addresses = [activity.split(" - ")[-1] for activity in activities]

        params = {
            "origins": "|".join(hotel_addresses),
            "destinations": "|".join(activity_addresses),
            "key": self.api_key,
            "mode": "driving",
            "units": "metric"
        }

        response = requests.get(self.BASE_URL, params=params)

        if response.status_code != 200:
            logger.error(f"Distance Matrix API error: {response.text}")
            return HumanMessage(content="Error: Unable to fetch distance data.")

        data = response.json()

        if data.get("status") != "OK":
            logger.error(f"Distance Matrix API issue: {data.get('error_message')}")
            return HumanMessage(content="Error: Invalid data from Distance Matrix API.")

        too_far = []
        for i, row in enumerate(data["rows"]):
            for j, element in enumerate(row["elements"]):
                if element["status"] == "OK":
                    distance_km = element["distance"]["value"] / 1000
                    if distance_km > threshold_km:
                        too_far.append((hotel_addresses[i], activity_addresses[j], distance_km))

        if too_far:
            msg = "Some hotels are too far from activities:\n"
            for hotel, activity, dist in too_far:
                msg += f"- Hotel at '{hotel}' is {dist:.1f} km away from activity at '{activity}'.\n"
            msg += "Recommend searching for closer hotels."
            return HumanMessage(content=msg)

        return HumanMessage(content="All hotels are within acceptable proximity to activities.")
