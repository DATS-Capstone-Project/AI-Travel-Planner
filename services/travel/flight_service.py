
import logging
from typing import Dict, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from datetime import datetime
from utils.flight_util import LLMAirportCodeAgent
from config.settings import OPENAI_API_KEY, SERP_API_KEY
from itertools import product
import aiohttp
import ssl
import certifi

logger = logging.getLogger(__name__)

FLIGHT_ADVISOR_PROMPT = """
You are an experienced travel advisor specializing in flight recommendations. You have a friendly, conversational style and genuinely want to help travelers find the best options for their journey.

### Your Response Format:
You MUST follow this EXACT format for your response:

1. Begin with a warm greeting that acknowledges the traveler's upcoming trip.
2. Organize the flights into groups of flights by time of day (Morning, Afternoon, Evening) based on their departure times.
3. For EACH flight option, provide the following details in the EXACT format:
   - **Airline Name**
     - **Price:** [Price with currency symbol]
     - **Total Duration:** [Total duration in hr and min format]
     - **Trip Type:** [Direct or Connecting]  
       (If connecting, mention the number of stops.)
     - For each flight segment (if the flight has multiple segments), include:
         - **Segment [Segment Number]: [Flight Number] - [Airline Name] ([Travel Class])**
             - **Departure:** [Departure Code] - [Departure Airport] at [Time]
             - **Arrival:** [Arrival Code] - [Arrival Airport] at [Time]
             - **Segment Duration:** [Duration]
             - **Aircraft:** [Aircraft]
             - **Legroom:** [Legroom details]
             - **Delay Notice:** If the segment is often delayed (30+ minutes), include a warning note.
             - **Features:** List key features if available.
     - **Layovers:** If applicable, list each layover with its airport, name, and formatted duration.
     - **Additional Information:** Include any extra details provided.
4. End your response with personalized recommendations that reference specific flights by their actual airline names and departure times, offering targeted advice based on the flight details provided.

### CRITICAL INSTRUCTIONS:
- You MUST ONLY use the EXACT flight data provided in the input. DO NOT invent or alter any flight information.
- Maintain precision with all details: airline names, times, prices, durations, and any additional flight attributes.
- NEVER use generic labels like "Flight A" or "Flight B or Option 1 or Option 2." Always reference the specific flight details by thier name.
- Group flights accurately by the departure time of day.
- Assume the flight data represents round-trip journeys;
- If a flight is direct, clearly state it; if it is connecting, specify the number of stops and include segment details.
- Include all additional details such as carbon emissions and extra features exactly as provided.

### Flight Data:
#### Flight Options:
{flight_options}

{context}

Remember to treat this as a real conversation where you're genuinely helping the traveler choose the best flight options based solely on the provided data.
"""


class FlightService:
    """Service for handling flight-related operations using Amadeus API with integrated prompt engineering for flight selection."""

    def __init__(self):
        """
        Initialize the Amadeus client and the LLM client using environment variables.
        """
        self.flight_data = []


    def _format_duration(self, minutes):
        """Convert duration from minutes to hours and minutes format."""
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours}h {mins}m"

    def _format_datetime(self, datetime_str):
        """Format datetime string to a more readable format."""
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%a, %b %d, %I:%M %p")

    def _get_safe_value(self, dictionary, keys, default=None):
        """Safely retrieve a value from a nested dictionary."""
        if not isinstance(keys, list):
            keys = [keys]

        current = dictionary
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current
    def extract_flight_details(self):
        """Extract and organize key details from the flight data."""
        if not self.flight_data:
            raise ValueError("No flight data loaded. Call load_flight_data() first.")

        flight_options = []

        for i, option in enumerate(self.flight_data, 1):
            flight_segments = []

            # Process each flight segment
            for flight in option.get("flights", []):
                # Extract departure information
                departure_airport = flight.get("departure_airport", {})
                departure_name = self._get_safe_value(departure_airport, "name", "Unknown")
                departure_id = self._get_safe_value(departure_airport, "id", "???")
                departure_time = self._get_safe_value(departure_airport, "time")

                if departure_time:
                    formatted_departure_time = self._format_datetime(departure_time)
                else:
                    formatted_departure_time = "Unknown"

                # Extract arrival information
                arrival_airport = flight.get("arrival_airport", {})
                arrival_name = self._get_safe_value(arrival_airport, "name", "Unknown")
                arrival_id = self._get_safe_value(arrival_airport, "id", "???")
                arrival_time = self._get_safe_value(arrival_airport, "time")

                if arrival_time:
                    formatted_arrival_time = self._format_datetime(arrival_time)
                else:
                    formatted_arrival_time = "Unknown"

                # Extract flight details
                duration = self._get_safe_value(flight, "duration")
                formatted_duration = self._format_duration(duration) if duration else "Unknown"

                segment = {
                    "airline": self._get_safe_value(flight, "airline", "Unknown"),
                    "flight_number": self._get_safe_value(flight, "flight_number", "Unknown"),
                    "departure": {
                        "airport": departure_name,
                        "code": departure_id,
                        "time": formatted_departure_time,
                        "raw_time": departure_time
                    },
                    "arrival": {
                        "airport": arrival_name,
                        "code": arrival_id,
                        "time": formatted_arrival_time,
                        "raw_time": arrival_time
                    },
                    "duration": formatted_duration,
                    "duration_minutes": duration,
                    "aircraft": self._get_safe_value(flight, "airplane", "Unknown"),
                    "features": self._get_safe_value(flight, "extensions", []),
                    "legroom": self._get_safe_value(flight, "legroom", "Unknown"),
                    "often_delayed": self._get_safe_value(flight, "often_delayed_by_over_30_min", False),
                    "travel_class": self._get_safe_value(flight, "travel_class", "Economy"),
                    "airline_logo": self._get_safe_value(flight, "airline_logo", None)
                }
                flight_segments.append(segment)

            # Process layover information
            layovers = []
            for layover in option.get("layovers", []):
                layover_info = {
                    "name": self._get_safe_value(layover, "name", "Unknown"),
                    "id": self._get_safe_value(layover, "id", "???"),
                    "duration": self._get_safe_value(layover, "duration", 0),
                    "formatted_duration": self._format_duration(self._get_safe_value(layover, "duration", 0))
                }
                layovers.append(layover_info)

            # Extract carbon emissions data
            carbon_data = option.get("carbon_emissions", {})
            if carbon_data:
                carbon_info = {
                    "this_flight": self._get_safe_value(carbon_data, "this_flight", 0),
                    "typical_for_this_route": self._get_safe_value(carbon_data, "typical_for_this_route", 0),
                    "difference_percent": self._get_safe_value(carbon_data, "difference_percent", 0),
                    "formatted_emissions": f"{self._get_safe_value(carbon_data, 'this_flight', 0) / 1000:.1f} kg"
                }
            else:
                carbon_info = {}

            # Create flight option summary
            total_duration = self._get_safe_value(option, "total_duration", 0)
            flight_option = {
                "option_number": i,
                "price": f"${self._get_safe_value(option, 'price', 0)}",
                "raw_price": self._get_safe_value(option, 'price', 0),
                "total_duration": self._format_duration(total_duration) if total_duration else "Unknown",
                "total_duration_minutes": total_duration,
                "airline": self._get_safe_value(flight_segments[0], "airline",
                                                "Unknown") if flight_segments else "Unknown",
                "segments": flight_segments,
                "layovers": layovers,
                "carbon_emissions": carbon_info,
                "extensions": self._get_safe_value(option, "extensions", []),
                "trip_type": self._get_safe_value(option, "type", "One way"),
                "airline_logo": self._get_safe_value(option, "airline_logo", None),
                "departure_token": self._get_safe_value(option, "departure_token", None)
            }

            flight_options.append(flight_option)

        return flight_options

    def create_structured_summary(self, flight_options=None):
        """Create a structured summary of flight options without using the AI model."""
        if flight_options is None:
            flight_options = self.extract_flight_details()

        summaries = []

        for option in flight_options:
            summary = f"Option {option['option_number']}: {option['airline']}\n"
            summary += f"Price: {option['price']}\n"
            summary += f"Duration: {option['total_duration']}\n"
            summary += f"Trip Type: {option['trip_type']}\n"

            # Direct vs. connecting flight
            if len(option['segments']) == 1:
                summary += "Direct Flight\n"
            else:
                summary += f"Connecting Flight with {len(option['segments']) - 1} layover(s)\n"

            # Segment details
            for i, segment in enumerate(option['segments'], 1):
                if len(option['segments']) > 1:
                    summary += f"\nSegment {i}: "

                summary += f"{segment['flight_number']} - {segment['airline']} ({segment['travel_class']})\n"
                summary += f"  Depart: {segment['departure']['code']} - {segment['departure']['airport']} ({segment['departure']['time']})\n"
                summary += f"  Arrive: {segment['arrival']['code']} - {segment['arrival']['airport']} ({segment['arrival']['time']})\n"
                summary += f"  Duration: {segment['duration']}\n"
                summary += f"  Aircraft: {segment['aircraft']}\n"
                summary += f"  Legroom: {segment['legroom']}\n"

                if segment['often_delayed']:
                    summary += "  ⚠️ Often delayed by 30+ minutes\n"

                # Key features
                if segment['features']:
                    key_features = segment['features']
                    if key_features:
                        summary += "  Features: " + "\n    • " + "\n    • ".join(key_features) + "\n"

            # Layover information
            if option['layovers']:
                summary += "\nLayovers:\n"
                for layover in option['layovers']:
                    summary += f"  {layover['name']} ({layover['id']}): {layover['formatted_duration']}\n"

            # Carbon emissions
            if option['carbon_emissions']:
                emission_info = option['carbon_emissions']
                comparison = ""
                if 'difference_percent' in emission_info:
                    diff = emission_info['difference_percent']
                    if diff < 0:
                        comparison = f" ({abs(diff)}% below average)"
                    else:
                        comparison = f" ({diff}% above average)"

                if 'formatted_emissions' in emission_info:
                    summary += f"\nCarbon Emissions: {emission_info['formatted_emissions']}{comparison}\n"

            # Additional information
            if option['extensions']:
                summary += "\nAdditional Information:\n"
                for ext in option['extensions']:
                    summary += f"  • {ext}\n"

            summaries.append(summary)

        return summaries
    async def get_best_flight(self, extracted_details: Dict[str, Any]) -> str:
        """
        Query the Google Flight website real time for flight offers using the extracted trip details,
        compute key metrics (cheapest, fewest layovers, shortest duration, best options per cabin if available),
        and use prompt engineering to generate a detailed plain language flight summary message.

        Args:
            extracted_details: A dictionary containing keys such as 'origin', 'destination', 'start_date', 'travelers'.

        Returns:
            A plain text string summarizing the flight offers with exact details for each offer.
        """
        origin = extracted_details.get("origin", "")
        destination = extracted_details.get("destination", "")
        start_date = extracted_details.get("start_date", "")
        end_date = extracted_details.get("end_date", "")
        travelers = extracted_details.get("travelers", 1)

        await self.load_flight_data(origin, destination, start_date, end_date, travelers)

        # Extract flight details
        flight_options = self.extract_flight_details()

        # Generate structured summaries
        structured_summaries = self.create_structured_summary(flight_options)

        flight_res = await self.get_flight_advisor_response(structured_summaries)

        return flight_res

    async def get_flight_advisor_response(self, flight_options, context=None):
        """Get flight advisor response based on scraped flight data."""
        context_str = f"\n### Additional Context:\n{context}" if context else ""

        prompt = FLIGHT_ADVISOR_PROMPT.format(
            flight_options=flight_options,
            context=context_str
        )
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5, openai_api_key=OPENAI_API_KEY)
        messages = [HumanMessage(content=prompt)]
        print("Generating flight advisor response...")
        response_llm = await llm.ainvoke(messages)
        advisor_response = response_llm.content.strip()

        print("Flight advisor response generated")
        return advisor_response

    async def load_flight_data(self, origin, destination, start_date, end_date, travelers):
        """
        Load flight data from multiple sources: file, JSON string, or API.

        Returns:
            list: Loaded flight data
        """
        # Define your lists of departure and arrival IDs.
        departure_ids = origin
        arrival_ids = destination

        # Base parameters that remain constant for all API calls.
        base_params = {
            "engine": "google_flights",
            "outbound_date": start_date,
            "return_date": end_date,
            "currency": "USD",
            "adults": travelers,
            "hl": "en",
            "deep_search": "true",
            "api_key": SERP_API_KEY
        }

        # Initialize an empty list to collect flight data.
        all_flights = []
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        async with aiohttp.ClientSession() as session:
            # Iterate over every combination of departure and arrival.
            for dep, arr in product(departure_ids, arrival_ids):
                # Create a new parameters dictionary for each request.
                params = base_params.copy()
                params["departure_id"] = dep
                params["arrival_id"] = arr

                # Make the API request.
                async with session.get('https://serpapi.com/search', params=params, ssl=ssl_context) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        # Check for "best_flights" first; otherwise, use "other_flights".
                        if "best_flights" in response:
                            all_flights.extend(response["best_flights"])
                        elif "other_flights" in response:
                            all_flights.extend(response["other_flights"])
                    else:
                        # Log an error or handle failure as needed.
                        logger.error(f"Failed to load flights for dep: {dep}, arr: {arr}. HTTP Status: {resp.status}")

        # Optionally assign to a class attribute if inside a class.
        self.flight_data = all_flights
        return self.flight_data

    async def get_flights(self, origin: str, destination: str, start_date: str, end_date: str,
                          travelers: int) -> str:
        """
        A wrapper method to allow the supervisor to call get_flights with keyword arguments.
        It builds an extracted_details dictionary and calls the underlying get_best_flight logic.
        """

        Origin_airport_codes = LLMAirportCodeAgent().get_airport_info(city_name=origin)
        Destination_airport_codes = LLMAirportCodeAgent().get_airport_info(city_name=destination)

        extracted_details = {
            "origin": Origin_airport_codes['airport_codes'],
            "destination": Destination_airport_codes['airport_codes'],
            "start_date": start_date,
            "end_date": end_date,
            "travelers": travelers
        }
        return await self.get_best_flight(extracted_details)

    def format_date(self, date_str):
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{date_obj.strftime('%Y')} {date_obj.day}, {date_obj.year}"
