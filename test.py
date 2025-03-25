# test_activity_service.py

import os
from dotenv import load_dotenv
from services.travel.activity_service import ActivityService

def main():
    # Load environment variables (ensure your .env file contains GOOGLE_PLACES_API_KEY)
    load_dotenv()

    # Create an instance of ActivityService
    activity_service = ActivityService()

    # Define test parameters
    destination = "Paris"  # Change this as needed
    preferences = None     # You can also set this to something like "art museums" if desired

    # Get activity recommendations
    activities = activity_service.get_activities(destination, preferences)

    # Print the results
    print("Activity Recommendations:")
    print(activities)

if __name__ == "__main__":
    main()
