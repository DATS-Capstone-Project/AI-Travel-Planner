# test_flight_agent.py

import os
from services.travel.flight_service import FlightService

def main():
    # Set environment variables for testing (optional if already set in your .env file)
    os.environ["AMADEUS_API_KEY"] = "YourAmadeusAPIKeyHere"
    os.environ["AMADEUS_API_SECRET"] = "YourAmadeusAPISecretHere"
    
    # Initialize the FlightService
    flight_service = FlightService()

    # Define test parameters: you can use either city names or IATA codes.
    origin = "New York"       # Will be resolved to an IATA code (e.g., NYC)
    destination = "London"    # Will be resolved to an IATA code (e.g., LON)
    start_date = "2025-03-25"   # Departure date in YYYY-MM-DD format
    travelers = 1             # Number of adult travelers

    # Call the flight agent
    result = flight_service.get_flights(origin, destination, start_date, travelers)
    
    # Print the results
    print("Flight search result:")
    print(result)

if __name__ == "__main__":
    main()
