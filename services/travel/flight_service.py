# services/travel/flight_service.py

import os
import json
import logging
import re
from typing import Dict, Any, List, Optional
from amadeus import Client, ResponseError
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
import asyncio

load_dotenv()

logger = logging.getLogger(__name__)

def parse_duration(duration_str: str) -> int:
    """
    Parse an ISO 8601 duration string (e.g., 'PT19H45M') and return total minutes.
    """
    hours = re.search(r'(\d+)H', duration_str)
    minutes = re.search(r'(\d+)M', duration_str)
    total = 0
    if hours:
        total += int(hours.group(1)) * 60
    if minutes:
        total += int(minutes.group(1))
    return total

class FlightService:
    """Service for handling flight-related operations using Amadeus API with integrated prompt engineering for flight selection."""

    def __init__(self):
        """
        Initialize the Amadeus client and the LLM client using environment variables.
        """
        self.amadeus = Client(
            client_id=os.getenv("AMADEUS_CLIENT_ID"),
            client_secret=os.getenv("AMADEUS_CLIENT_SECRET"),
            log_level="debug"
        )
        self.llm = ChatOpenAI(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-3.5-turbo", temperature=0)

    def _get_iata_code(self, location: str) -> str:
        """
        Resolve a city name to an IATA code using Amadeus API. If the input is already a 3-letter code,
        it returns the code in uppercase. If no code is found via the API, a fallback mapping is used.
        """
        if len(location) == 3 and location.isalpha():
            return location.upper()

        fallback_mapping = {
            "NEW YORK CITY": "NYC",
            "NEW YORK": "NYC",
            "BANGALORE": "BLR",
            "BENGALURU": "BLR",
            "BENAGLURU": "BLR",  # Handling common misspelling
            "LOS ANGELES": "LAX",
            "CHICAGO": "CHI",
            # Extend mapping as needed.
        }
        
        loc_upper = location.upper().strip()
        refined_keyword = loc_upper.replace(" CITY", "").strip()

        try:
            response = self.amadeus.reference_data.locations.get(keyword=refined_keyword, subType="CITY")
            data = response.data
            if data and "iataCode" in data[0]:
                return data[0]["iataCode"].upper()
            else:
                logger.warning(f"No IATA code found for location: {location} using refined keyword '{refined_keyword}'.")
                if loc_upper in fallback_mapping:
                    return fallback_mapping[loc_upper]
                return loc_upper
        except ResponseError as error:
            logger.error(f"Error fetching IATA code for {location}: {error}")
            if loc_upper in fallback_mapping:
                return fallback_mapping[loc_upper]
            return loc_upper

    async def get_best_flight(self, extracted_details: Dict[str, Any]) -> str:
        """
        Use extracted trip details to query the Amadeus API for flight offers,
        compute key metrics (cheapest, lowest layovers, shortest duration, best options per cabin if available)
        and then use prompt engineering to generate a detailed plain language flight summary message.
        
        Args:
            extracted_details: A dictionary containing keys such as 'origin', 'destination', 'start_date', 'travelers'.
                               
        Returns:
            A plain text string summarizing the flight offers with exact details for each offer.
        """
        origin = extracted_details.get("origin", "")
        destination = extracted_details.get("destination", "")
        start_date = extracted_details.get("start_date", "")
        travelers = extracted_details.get("travelers", 1)
        
        origin_code = self._get_iata_code(origin)
        destination_code = self._get_iata_code(destination)
        
        query_payload = {
            "originLocationCode": origin_code,
            "destinationLocationCode": destination_code,
            "departureDate": start_date,
            "adults": travelers,
            "currencyCode": "USD",
            "max": 5,
        }
        
        logger.info(f"Querying flights with payload: {query_payload}")
        
        try:
            response = self.amadeus.shopping.flight_offers_search.get(**query_payload)
            flight_offers = response.data
            # Capture additional dictionary info if available.
            dictionaries = response.result.get("dictionaries", {}) if hasattr(response, "result") and isinstance(response.result, dict) else {}
            if not flight_offers:
                return f"No flights found for {origin_code} → {destination_code} on {start_date}."
        except ResponseError as error:
            logger.error(f"Amadeus Flight API error: {error}")
            return f"Error fetching flights from Amadeus: {error}"
        
        # Process each offer to extract key details.
        processed_offers: List[Dict[str, Any]] = []
        for idx, offer in enumerate(flight_offers, start=1):
            try:
                price = float(offer["price"]["grandTotal"])
            except Exception:
                price = float(offer["price"]["total"])
            currency = offer["price"]["currency"]
            
            itinerary = offer.get("itineraries", [])[0]
            duration_str = itinerary.get("duration", "PT0M")
            total_duration = parse_duration(duration_str)
            segments = itinerary.get("segments", [])
            layovers = len(segments) - 1 if segments else 0
            
            cabin_class = "N/A"
            if "travelerPricings" in offer and offer["travelerPricings"]:
                cabin_class = offer["travelerPricings"][0].get("cabin", "N/A")
            
            segment_details = []
            for seg in segments:
                segment_details.append({
                    "carrier": seg.get("carrierCode", "N/A"),
                    "flight_number": seg.get("flightNumber", "N/A"),
                    "departure_iata": seg["departure"].get("iataCode", "N/A"),
                    "departure_time": seg["departure"].get("at", "N/A"),
                    "arrival_iata": seg["arrival"].get("iataCode", "N/A"),
                    "arrival_time": seg["arrival"].get("at", "N/A"),
                    "aircraft": seg.get("aircraft", {}).get("code", "N/A")
                })
            
            processed_offers.append({
                "price": price,
                "currency": currency,
                "total_duration_minutes": total_duration,
                "layovers": layovers,
                "cabin": cabin_class,
                "segments": segment_details
            })
        
        raw_offers_json = json.dumps(processed_offers, indent=2)
        logger.info(f"Processed flight offers JSON: {raw_offers_json}")
        
        # Build a prompt for the LLM to generate a plain language summary message.
        prompt = (
            "You are a seasoned travel advisor with expertise in flight planning. "
            "Given the following JSON data of flight offers, generate a detailed, plain language summary that includes the exact details of each flight offer. "
            "For each flight offer, include the following details:\n"
            "- Price (with currency)\n"
            "- Total flight duration (in minutes)\n"
            "- Number of layovers\n"
            "- Cabin class\n"
            "- For each segment, include the carrier name, flight number, aircraft model (if available), departure and arrival airport codes, and departure and arrival times\n"
            "Also, if there are any alternative or nearby airport options based on the provided dictionaries, mention them.\n\n"
            "Do not refer to the offers as 'Option 1', 'Option 2', etc. Instead, provide a clear summary for each offer with all the above details.\n\n"
            "Here is the flight offers JSON data:\n\n"
            f"{raw_offers_json}\n\n"
            "Return the summary as a plain text message."
        )
        
        messages = [HumanMessage(content=prompt)]
        response_llm = await self.llm.ainvoke(messages)
        human_message = response_llm.content.strip()
        logger.info(f"LLM generated human message: {human_message}")
        
        return human_message

