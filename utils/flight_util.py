import json
import os
from typing import List, Dict, Union, Optional
from config.settings import OPENAI_API_KEY, CONVERSATION_MODEL
import openai

class LLMAirportCodeAgent:
    """
    An agent that uses LLM capabilities to retrieve airport codes for cities.
    No databases or hardcoded mappings - relies entirely on the LLM's knowledge.
    """

    def __init__(self):
        """
        Initialize the LLM-based airport code agent.

        Args:
            openai_api_key: OpenAI API key (optional, will check environment variable)
        """
        # Set up the OpenAI client
        self.openai_api_key = OPENAI_API_KEY

        if not self.openai_api_key:
            raise ValueError(
                "OpenAI API key is required. Provide it as an argument or set the OPENAI_API_KEY environment variable.")

        try:
            self.client = openai.OpenAI(api_key=self.openai_api_key)
        except ImportError:
            raise ImportError("The openai package is required. Install it with 'pip install openai'.")

    def get_airport_codes(self, city_name: str) -> List[str]:
        """
        Get airport codes for a city using LLM.

        Args:
            city_name: Name of the city

        Returns:
            List of airport codes for the city
        """
        result = self._query_llm(city_name)
        return result["airport_codes"]

    def get_primary_airport_code(self, city_name: str) -> Optional[str]:
        """
        Get the primary airport code for a city.

        Args:
            city_name: Name of the city

        Returns:
            Primary airport code or None if not found
        """
        result = self._query_llm(city_name)
        if result["airport_codes"]:
            return result["airport_codes"][0]
        return None

    def get_airport_info(self, city_name: str) -> Dict[str, Union[str, List[Dict]]]:
        """
        Get detailed airport information for a city.

        Args:
            city_name: Name of the city

        Returns:
            Dictionary with airport information
        """
        return self._query_llm(city_name, include_names=True)

    def _query_llm(self, city_name: str, include_names: bool = False) -> Dict:
        """
        Query the LLM for airport information.

        Args:
            city_name: Name of the city
            include_names: Whether to include airport names in the response

        Returns:
            Dictionary with the LLM's response
        """
        # Craft an effective prompt for the LLM
        prompt = self._create_prompt(city_name, include_names)

        try:
            # Query the LLM
            response = self.client.chat.completions.create(
                model=CONVERSATION_MODEL,  # Or another appropriate model
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]}
                ],
                response_format={"type": "json_object"}
            )

            # Parse the response
            content = response.choices[0].message.content
            result = json.loads(content)

            # Ensure consistent return format
            if "airport_codes" not in result:
                result["airport_codes"] = []

            if include_names and "airports" not in result:
                result["airports"] = []

            return result

        except Exception as e:
            print(f"Error querying LLM: {str(e)}")
            if include_names:
                return {"status": "error", "message": str(e), "airport_codes": [], "airports": []}
            else:
                return {"status": "error", "message": str(e), "airport_codes": []}

    def _create_prompt(self, city_name: str, include_names: bool) -> Dict[str, str]:
        """
        Create an effective prompt for the LLM.

        Args:
            city_name: Name of the city
            include_names: Whether to include airport names

        Returns:
            Dictionary with system and user prompts
        """
        system_prompt = """
You are an expert on global airports and their IATA codes. Your task is to provide accurate airport codes for cities worldwide.
- Only respond with valid IATA codes (3-letter codes)
- List multiple codes if a city has multiple airports
- Always list the most important/busiest airport first
- Format your response as a valid JSON object
- Do not include explanations outside of the JSON

If you're unsure about an airport code, don't guess - only include codes you're confident about.
"""

        if include_names:
            system_prompt += """
Your response should be a JSON object with these fields:
{
  "status": "success" or "not_found",
  "message": a short status message,
  "airport_codes": ["XXX", "YYY", ...],
  "airports": [
    {"code": "XXX", "name": "Full Airport Name"},
    ...
  ]
}
"""
        else:
            system_prompt += """
Your response should be a JSON object with these fields:
{
  "status": "success" or "not_found",
  "message": a short status message,
  "airport_codes": ["XXX", "YYY", ...]
}
"""

        user_prompt = f"What are the airport codes for {city_name}?"

        return {
            "system": system_prompt,
            "user": user_prompt
        }
