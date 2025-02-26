import logging
from typing import Optional

# Configure logger
logger = logging.getLogger(__name__)


class ActivityService:
    """Service for handling activity-related operations"""

    def get_activities(self, destination: str, preferences: Optional[str] = None) -> str:
        """
        Get activity recommendations for a destination

        Args:
            destination: Destination city
            preferences: User activity preferences (optional)

        Returns:
            Activity recommendations string
        """
        logger.info(f"Getting activities in {destination} with preferences: {preferences}")

        # In a real implementation, this would call an external API
        # For now, we return mock data based on the destination
        activities = self._get_mock_activities_for_destination(destination)

        # If preferences are provided, filter activities
        if preferences:
            return f"Activities in {destination} matching '{preferences}': {activities}"
        else:
            return f"Popular activities in {destination}: {activities}"

    def _get_mock_activities_for_destination(self, destination: str) -> str:
        """Get mock activities based on destination"""
        destination = destination.lower()

        # Return different activities based on the destination
        if "new york" in destination:
            return "Museum of Modern Art, Central Park Tour, Empire State Building"
        elif "paris" in destination:
            return "Eiffel Tower, Louvre Museum, Seine River Cruise"
        elif "tokyo" in destination:
            return "Shinjuku Gyoen, Tokyo Skytree, Meiji Shrine"
        elif "london" in destination:
            return "British Museum, Tower of London, Westminster Abbey"
        elif "rome" in destination:
            return "Colosseum, Vatican Museums, Trevi Fountain"
        elif "istanbul" in destination:
            return "Hagia Sophia, Topkapi Palace, Grand Bazaar, Bosphorus Cruise"
        else:
            return "City Tour, Local Museums, Cultural Experiences"