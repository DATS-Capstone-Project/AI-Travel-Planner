from typing import Dict


class StateManager:
    def __init__(self):
        self.sessions: Dict[str, dict] = {}

    def get_session(self, session_id: str) -> dict:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "destination": None,
                "start_date": None,
                "end_date": None,
                "travelers": None,
                "budget": None,
                "preferences": None,
            }
        return self.sessions[session_id]

    def update_session(self, session_id: str, updates: dict):
        session = self.get_session(session_id)
        session.update(updates)
        return session


state_manager = StateManager()
