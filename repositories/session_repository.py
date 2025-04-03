import logging
import json
from typing import Dict, Optional, List
from redis import Redis
from models.trip_details import TripDetails

# Configure logger
logger = logging.getLogger(__name__)


class SessionRepository:
    """Repository for managing session data using Redis"""

    def __init__(self, redis_client: Redis):
        """Initialize with a Redis client

        Args:
            redis_client: Connected Redis client
        """
        self.redis = redis_client
        # Default expiration for session data (24 hours)
        self.default_expiry = 86400

    def _get_thread_key(self, session_id: str) -> str:
        """Get Redis key for thread ID"""
        return f"session:{session_id}:thread_id"

    def _get_confirmed_key(self, session_id: str) -> str:
        """Get Redis key for confirmation status"""
        return f"session:{session_id}:confirmed"

    def _get_trip_details_key(self, session_id: str) -> str:
        """Get Redis key for trip details"""
        return f"session:{session_id}:trip_details"

    def _get_messages_key(self, session_id: str) -> str:
        """Get Redis key for message history"""
        return f"session:{session_id}:messages"

    def get_thread_id(self, session_id: str) -> Optional[str]:
        """Get thread ID for a session"""
        thread_id = self.redis.get(self._get_thread_key(session_id))
        return thread_id.decode('utf-8') if thread_id else None

    def set_thread_id(self, session_id: str, thread_id: str) -> None:
        """Set thread ID for a session"""
        self.redis.set(self._get_thread_key(session_id), thread_id, ex=self.default_expiry)

    def is_confirmed(self, session_id: str) -> bool:
        """Check if user has confirmed trip details"""
        confirmed = self.redis.get(self._get_confirmed_key(session_id))
        return confirmed == b'1' if confirmed else False

    def set_confirmed(self, session_id: str, confirmed: bool) -> None:
        """Set confirmation status for a session"""
        self.redis.set(
            self._get_confirmed_key(session_id),
            '1' if confirmed else '0',
            ex=self.default_expiry
        )

    def get_trip_details(self, session_id: str) -> TripDetails:
        """Get trip details for a session"""
        try:
            details_json = self.redis.get(self._get_trip_details_key(session_id))

            if details_json:
                details_dict = json.loads(details_json)
                return TripDetails.from_dict(details_dict)
        except Exception as e:
            logger.error(f"Error retrieving trip details for session {session_id}: {e}")

        # Return default TripDetails if none exists or an error occurred
        return TripDetails()

    def update_trip_details(self, session_id: str, details: dict) -> TripDetails:
        """Update trip details for a session"""
        current = self.get_trip_details(session_id)
        updated = current.update(details)

        # Serialize and save to Redis
        self.redis.set(
            self._get_trip_details_key(session_id),
            json.dumps(updated.to_dict()),
            ex=self.default_expiry
        )

        logger.info(f"Updated trip details for session {session_id}: {updated.to_dict()}")
        return updated

    def get_message_history(self, session_id: str) -> List[Dict]:
        """Get message history for a session"""
        messages_json = self.redis.lrange(self._get_messages_key(session_id), 0, -1)
        return [json.loads(msg) for msg in messages_json]

    def add_message(self, session_id: str, message: Dict) -> None:
        """Add a message to the session history

        Args:
            session_id: The session identifier
            message: Dictionary containing 'role' (user/assistant) and 'content'
        """
        message_key = self._get_messages_key(session_id)
        self.redis.rpush(message_key, json.dumps(message))
        self.redis.expire(message_key, self.default_expiry)

        messages_count = self.redis.llen(message_key)
        logger.info(f"Added message to session {session_id}, total messages: {messages_count}")

    def reset_session(self, session_id: str) -> None:
        """Reset a session by deleting all associated keys"""
        keys_to_delete = [
            self._get_thread_key(session_id),
            self._get_confirmed_key(session_id),
            self._get_trip_details_key(session_id),
            self._get_messages_key(session_id)
        ]

        # Delete all keys for this session
        if keys_to_delete:
            self.redis.delete(*keys_to_delete)

        logger.info(f"Reset session {session_id}")

    def set_session_expiry(self, session_id: str, seconds: int = None) -> None:
        """Set expiration for all session-related keys

        Args:
            session_id: The session identifier
            seconds: Time in seconds until expiration (uses default_expiry if None)
        """
        expiry = seconds if seconds is not None else self.default_expiry
        keys = [
            self._get_thread_key(session_id),
            self._get_confirmed_key(session_id),
            self._get_trip_details_key(session_id),
            self._get_messages_key(session_id)
        ]

        # Set expiration for each key
        for key in keys:
            if self.redis.exists(key):
                self.redis.expire(key, expiry)