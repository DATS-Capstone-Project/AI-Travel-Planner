import logging
from typing import Dict, Optional
from models.trip_details import TripDetails

# Configure logger
logger = logging.getLogger(__name__)


class SessionRepository:
    """Repository for managing session data"""

    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.threads: Dict[str, str] = {}  # Maps session_id to OpenAI thread_id
        self.user_confirmed: Dict[str, bool] = {}  # Tracks confirmation status per session
        self.trip_details: Dict[str, TripDetails] = {}  # Stores trip details per session

    def get_thread_id(self, session_id: str) -> Optional[str]:
        """Get thread ID for a session"""
        return self.threads.get(session_id)

    def set_thread_id(self, session_id: str, thread_id: str) -> None:
        """Set thread ID for a session"""
        self.threads[session_id] = thread_id

    def is_confirmed(self, session_id: str) -> bool:
        """Check if user has confirmed trip details"""
        return self.user_confirmed.get(session_id, False)

    def set_confirmed(self, session_id: str, confirmed: bool) -> None:
        """Set confirmation status for a session"""
        self.user_confirmed[session_id] = confirmed

    def get_trip_details(self, session_id: str) -> TripDetails:
        """Get trip details for a session"""
        if session_id not in self.trip_details:
            self.trip_details[session_id] = TripDetails()
        return self.trip_details[session_id]

    def update_trip_details(self, session_id: str, details: dict) -> TripDetails:
        """Update trip details for a session"""
        current = self.get_trip_details(session_id)
        updated = current.update(details)
        self.trip_details[session_id] = updated
        logger.info(f"Updated trip details for session {session_id}: {updated.to_dict()}")
        return updated

    def reset_session(self, session_id: str) -> None:
        """Reset a session"""
        if session_id in self.threads:
            del self.threads[session_id]
        if session_id in self.user_confirmed:
            del self.user_confirmed[session_id]
        if session_id in self.trip_details:
            del self.trip_details[session_id]
        logger.info(f"Reset session {session_id}")