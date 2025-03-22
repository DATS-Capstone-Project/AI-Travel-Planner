import logging
from typing import Optional
from datetime import datetime
from config.settings import DEFAULT_BUDGET
from langchain_core.messages import HumanMessage


# Configure logger
logger = logging.getLogger(__name__)


class HotelService:
    """Service for handling hotel-related operations"""

    def get_hotels(self, destination: str, start_date: str, end_date: str, budget: Optional[int] = None) -> str:
        """
        Get hotel information for a trip

        Args:
            destination: Destination city
            start_date: Check-in date in YYYY-MM-DD format
            end_date: Check-out date in YYYY-MM-DD format
            budget: Budget per night in USD (optional)

        Returns:
            Hotel information string
        """
        # Use default budget if not provided
        if budget is None:
            budget = DEFAULT_BUDGET

        logger.info(f"Getting hotels in {destination} from {start_date} to {end_date} with budget ${budget}/night")

        # In a real implementation, this would call an external API
        # For now, we return mock data
        hotels_info = f"Hotels in {destination} from {start_date} to {end_date}: 4-star from ${budget // 2}/night"
        return HumanMessage(content=hotels_info)

    def calculate_nightly_budget(self, total_budget: int, start_date: str, end_date: str) -> int:
        """
        Calculate per-night budget from total trip budget

        Args:
            total_budget: Total budget for the trip
            start_date: Check-in date in YYYY-MM-DD format
            end_date: Check-out date in YYYY-MM-DD format

        Returns:
            Budget per night
        """
        try:
            # Calculate number of nights
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            nights = (end - start).days

            if nights <= 0:
                return DEFAULT_BUDGET

            # Allocate 60% of total budget to accommodation
            accommodation_budget = total_budget * 0.6

            # Calculate per-night budget
            per_night = int(accommodation_budget / nights)

            # Ensure minimum reasonable budget
            return max(per_night, 50)

        except Exception as e:
            logger.error(f"Error calculating nightly budget: {e}")
            return DEFAULT_BUDGET