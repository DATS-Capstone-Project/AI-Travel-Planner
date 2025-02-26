from abc import ABC, abstractmethod
from models.trip_details import TripDetails


class EntityExtractor(ABC):
    """Abstract base class for entity extraction strategies"""

    @abstractmethod
    def extract(self, message: str) -> TripDetails:
        """
        Extract travel details from a user message

        Args:
            message: The user's message text

        Returns:
            TripDetails object with extracted information
        """
        pass