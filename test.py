# test_flight_service.py

import os
import asyncio
from dotenv import load_dotenv
from services.travel.flight_service import FlightService

def main():
    load_dotenv()
    flight_service = FlightService()

    # Define sample extracted details.
    extracted_details = {
        "origin": "New York City",    # Expected to resolve to NYC via fallback.
        "destination": "Bengaluru",   # Expected to resolve to BLR via fallback.
        "start_date": "2025-03-21",     # Ensure this date is in the future relative to today.
        "travelers": 1
    }

    # Run the asynchronous get_best_flight method.
    flight_summary = asyncio.run(flight_service.get_best_flight(extracted_details))
    print("Flight Summary:")
    print(flight_summary)

if __name__ == "__main__":
    main()
