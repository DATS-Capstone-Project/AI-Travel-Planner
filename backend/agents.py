class FlightAgent:
    def get_flights(self, destination: str, start_date: str, travelers: int) -> str:
        return f"Flights to {destination} on {start_date} for {travelers} travelers: Economy from $300"


class HotelAgent:
    def get_hotels(self, destination: str, start_date: str, end_date: str, budget: int) -> str:
        return f"Hotels in {destination} from {start_date} to {end_date}: 4-star from ${budget // 2}/night"


class ActivityAgent:
    def get_activities(self, destination: str, preferences: str) -> str:
        return f"Activities in {destination}: Museum of Modern Art, Central Park Tour"


flight_agent = FlightAgent()
hotel_agent = HotelAgent()
activity_agent = ActivityAgent()
