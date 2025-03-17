# services/travel/flight_service.py

import os
import logging
from typing import Optional
from amadeus import Client, ResponseError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class FlightService:
    """Service for handling flight-related operations using Amadeus API."""

    def __init__(self):
        """
        Initialize the Amadeus client using environment variables.
        """
        self.amadeus = Client(
            client_id=os.getenv("AMADEUS_CLIENT_ID"),
            client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
            log_level="debug"
        )

    def _get_iata_code(self, location: str) -> str:
        """
        Resolve a city name to an IATA code using Amadeus API. If the input is already a 3-letter code,
        it returns the code in uppercase. If no code is found via the API, a fallback mapping is used.

        Args:
            location: City name or IATA code.

        Returns:
            IATA code in uppercase.
        """
        # If the input is already a valid IATA code, return it.
        if len(location) == 3 and location.isalpha():
            return location.upper()

        # Define a fallback mapping for common cities.
        fallback_mapping = {
            "NEW YORK CITY": "NYC",
            "NEW YORK": "NYC",
            "BANGALORE": "BLR",
            "BENGALURU": "BLR",
            "LOS ANGELES": "LAX",
            "CHICAGO": "CHI",
            # Add additional mappings as required.
        }
        
        loc_upper = location.upper().strip()

        # Attempt to refine the query keyword (e.g., remove the word "CITY")
        refined_keyword = loc_upper.replace(" CITY", "").strip()

        try:
            response = self.amadeus.reference_data.locations.get(keyword=refined_keyword, subType="CITY")
            data = response.data
            if data and "iataCode" in data[0]:
                return data[0]["iataCode"].upper()
            else:
                logger.warning(f"No IATA code found for location: {location} using refined keyword '{refined_keyword}'.")
                # Check fallback mapping if API returns empty data.
                if loc_upper in fallback_mapping:
                    return fallback_mapping[loc_upper]
                return loc_upper
        except ResponseError as error:
            logger.error(f"Error fetching IATA code for {location}: {error}")
            # In case of an error, check fallback mapping.
            if loc_upper in fallback_mapping:
                return fallback_mapping[loc_upper]
            return loc_upper

    def get_flights(self, origin: str, destination: str, start_date: str, travelers: int) -> str:
        """
        Query Amadeus API for flight offers from origin to destination on start_date,
        for the given number of travelers.

        Args:
            origin: City name or IATA code of the origin.
            destination: City name or IATA code of the destination.
            start_date: Departure date in 'YYYY-MM-DD' format.
            travelers: Number of adult travelers.

        Returns:
            A string summarizing flight offers, or an error message.
        """
        origin_code = self._get_iata_code(origin)
        destination_code = self._get_iata_code(destination)

        logger.info(
            f"Fetching flight data with Amadeus from {origin_code} to {destination_code} on {start_date} for {travelers} traveler(s)."
        )

        try:
            response = self.amadeus.shopping.flight_offers_search.get(
                originLocationCode=origin_code,
                destinationLocationCode=destination_code,
                departureDate=start_date,
                adults=travelers,
                currencyCode="USD",
                max=5  # Limit to a few flight offers for demonstration
            )

            flight_offers = response.data
            if not flight_offers:
                return f"No flights found for {origin_code} → {destination_code} on {start_date}."

            results_summary = []
            for idx, offer in enumerate(flight_offers, start=1):
                price = offer["price"]["grandTotal"]
                currency = offer["price"]["currency"]

                itineraries = offer.get("itineraries", [])
                if not itineraries:
                    continue

                first_itinerary = itineraries[0]
                segments = first_itinerary.get("segments", [])
                if not segments:
                    continue

                departure_iata = segments[0]["departure"].get("iataCode")
                departure_time = segments[0]["departure"].get("at")
                arrival_iata = segments[-1]["arrival"].get("iataCode")
                arrival_time = segments[-1]["arrival"].get("at")

                offer_text = (
                    f"Option {idx}:\n"
                    f" - Price: {price} {currency}\n"
                    f" - Departure: {departure_iata} at {departure_time}\n"
                    f" - Arrival: {arrival_iata} at {arrival_time}\n"
                )
                results_summary.append(offer_text)

            return "\n".join(results_summary)

        except ResponseError as error:
            logger.error(f"Amadeus Flight API error: {error}")
            return f"Error fetching flights from Amadeus: {error}"
