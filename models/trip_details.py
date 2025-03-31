from dataclasses import dataclass, field
from typing import Optional, Dict, List, ClassVar


@dataclass
class TripDetails:
    """Data model for trip details extracted from user messages"""
    origin: Optional[str] = None
    destination: Optional[str] = None
    start_date: Optional[str] = None  # ISO format: YYYY-MM-DD
    end_date: Optional[str] = None  # ISO format: YYYY-MM-DD
    travelers: Optional[int] = None
    budget: Optional[int] = None
    preferences: Optional[str] = None
    confidence_levels: Dict[str, str] = field(default_factory=dict)

    # Add a new method to check if dates need confirmation
    def needs_date_confirmation(self) -> bool:
        """Check if dates need explicit confirmation"""
        has_dates = self.start_date and self.end_date
        dates_inferred = (self.confidence_levels.get("start_date") == "inferred" or
                          self.confidence_levels.get("end_date") == "inferred")
        return has_dates and dates_inferred

    def to_dict(self) -> Dict:
        """Convert to dictionary, excluding None values"""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict) -> 'TripDetails':
        """Create a TripDetails instance from a dictionary"""
        # Filter the dictionary to only include valid fields
        valid_fields = {k: v for k, v in data.items() if k in cls.__annotations__}
        return cls(**valid_fields)

    def update(self, new_data: Dict) -> 'TripDetails':
        """Update fields from a dictionary, preserving existing values"""
        for key, value in new_data.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        return self

    def missing_required_fields(self) -> List[str]:
        """Return required fields that haven't been provided yet"""
        missing = []
        if not self.destination:
            missing.append("destination")
        if not self.origin:
            missing.append("origin")
        if not self.start_date:
            missing.append("start date")
        if not self.end_date:
            missing.append("end date")
        if not self.travelers:
            missing.append("number of travelers")
        return missing

    def missing_optional_fields(self) -> List[str]:
        """Return optional fields that haven't been provided yet"""
        missing = []
        if not self.budget:
            missing.append("budget")
        if not self.preferences:
            missing.append("activity preferences")
        return missing

    def is_ready_for_confirmation(self) -> bool:
        """Check if all required fields are complete and ready for confirmation"""
        return len(self.missing_required_fields()) == 0

    def is_complete(self) -> bool:
        """Check if all required and optional fields are filled"""
        return len(self.missing_required_fields()) == 0 and len(self.missing_optional_fields()) == 0

    def __str__(self) -> str:
        """String representation for logging and debugging"""
        fields = []
        if self.destination:
            fields.append(f"Destination: {self.destination}")
        if self.origin:
            fields.append(f"Origin: {self.origin}")
        if self.start_date:
            fields.append(f"Start Date: {self.start_date}")
        if self.end_date:
            fields.append(f"End Date: {self.end_date}")
        if self.travelers:
            fields.append(f"Travelers: {self.travelers}")
        if self.budget:
            fields.append(f"Budget: ${self.budget}")
        if self.preferences:
            fields.append(f"Preferences: {self.preferences}")

        if not fields:
            return "Empty Trip Details"
        return ", ".join(fields)