# test_hotel_service.py

import os
from dotenv import load_dotenv
from services.travel.hotel_service import HotelService

def main():
    # Load environment variables from your .env file
    load_dotenv()
    
    # Create an instance of the HotelService
    hotel_service = HotelService()
    
    # Define sample parameters:
    destination = "Paris"           # Change this to any destination you want to test
    start_date = "2025-03-23"         # Check-in date (YYYY-MM-DD)
    end_date = "2025-03-27"           # Check-out date (YYYY-MM-DD)
    # Optional: Specify a budget per night. If omitted, DEFAULT_BUDGET will be used.
    budget = 150  # Example: $150 per night
    
    # Call the get_hotels method and capture the result
    hotels_info = hotel_service.get_hotels(destination, start_date, end_date, budget)
    
    # Print the result to the console
    print("Hotel Options:")
    print(hotels_info)

if __name__ == "__main__":
    main()
