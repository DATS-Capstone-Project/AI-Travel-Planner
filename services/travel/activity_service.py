import requests
import logging
from langchain_core.messages import HumanMessage
from models.chat_models import AgentState
from tavily import TavilyClient
from openai import OpenAI
import os
import json
import time
from typing import Dict, List, TypedDict, Optional, Any
import re
import asyncio

# Configure logger
logger = logging.getLogger(__name__)


class ActivityService:
    """Service for handling activity-related operations using the Google Places API."""

    def __init__(self):
        # Initialize API clients
        self.tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def get_activities(self, destination: str, preferences: Optional[str] = None):
        """
        Get activity recommendations for a destination using the Google Places API.

        Args:
            destination: Destination city.
            preferences: User activity preferences (optional).

        Returns:
            A string summarizing activity recommendations.
        """
        target_dest = destination

        print(f"============================================================")
        print(f"  STARTING RESEARCH FOR: {target_dest}")
        if preferences:
            print(f"  WITH PREFERENCES: {preferences}")
        print(f"============================================================")

        # Run the research
        result = await self.research_destination(target_dest, preferences)

        if result.get("final_plan"):
            plan = result["final_plan"]

            print(f"============================================================")
            print(f"  RESEARCH COMPLETED SUCCESSFULLY")
            print(f"============================================================")

            print(f"\nTravel Guide: {plan.get('title')}")
            print(f"\nIntroduction: {plan.get('introduction')[:100]}...")
            return plan
        else:
            print(f"============================================================")
            print(f"  RESEARCH FAILED")
            print(f"============================================================")

            if result.get("error"):
                print(f"Error: {result['error']}")
            else:
                print("No final plan was generated and no specific error was reported.")

        return None

    async def research_destination(self, destination: str, preferences: Optional[str] = None) -> AgentState:
        """
        Direct implementation of the travel research workflow without LangGraph,
        incorporating user preferences if provided.

        Args:
            destination: The destination city to research
            preferences: Optional string containing user's activity and food preferences

        Returns:
            AgentState containing the research results and final plan
        """
        print(f"=== Starting travel research for {destination} ===")
        if preferences:
            print(f"=== With user preferences: {preferences} ===")
        start_time = time.time()

        # Initialize state
        state = AgentState(
            destination=destination,
            preferences=preferences if preferences else None,
            messages=[{"role": "assistant", "content": f"Starting travel research for {destination}..."}],
            research_topics=[],
            research_results={},
            curated_content={},
            final_plan={},
            error=None
        )

        try:
            # Step 1: Generate standard research topics
            print("Generating research topics...")

            # Standard topics regardless of preferences
            prompt = f"""
            You are a travel research supervisor. For the destination {destination}, 
            identify the top 3 categories of information we need to research about local foods 
            and the top 3 categories about local activities.

            Format your response as a JSON object with a key "topics" that contains an array of strings, 
            each representing a specific research topic. Be specific with your topics to get useful search results.

            Example format: {{"topics": ["Traditional breakfast foods in Barcelona", "Street food markets in Barcelona", ...]}}
            """

            response = self.openai.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "system", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.5
            )

            content = json.loads(response.choices[0].message.content)
            research_topics = content["topics"]

            # Step 1.5: Add preference-specific research topics if preferences exist
            if preferences:
                # Split preferences by commas, and, or other separators to identify distinct preferences
                print(f"Generating preference-specific research topics for: {preferences}")
                preference_items = [p.strip() for p in re.split(r'[,;&]|\s+and\s+', preferences)]

                # For each distinct preference, create a direct research topic
                preference_topics = []
                for item in preference_items:
                    if item:  # Skip empty items
                        # Create both a general and a specific topic for each preference
                        general_topic = f"Best {item} experiences in or near {destination}"
                        specific_topic = f"Visitor guide to {item} from {destination}"
                        preference_topics.extend([general_topic, specific_topic])

                # Add preference topics to main research topics
                research_topics.extend(preference_topics)
                print(f"Added {len(preference_topics)} preference-specific research topics")

            state["research_topics"] = research_topics
            state["messages"].append({
                "role": "assistant",
                "content": f"Research topics identified: {', '.join(research_topics)}"
            })
            print(f"Generated {len(research_topics)} research topics")

            # Step 2: Research each topic
            print("Researching topics...")
            for topic in research_topics:
                print(f"Researching: {topic}")
                try:
                    search_response = await asyncio.to_thread(
                        self.tavily.search,
                        query=topic,
                        search_depth="advanced",
                        include_answer=True,
                        include_raw_content=True,
                        max_results=5
                    )

                    state["research_results"][topic] = search_response
                    state["messages"].append({
                        "role": "assistant",
                        "content": f"Completed research on: {topic}. Found {len(search_response['results'])} sources."
                    })
                    print(f"Research complete for {topic}")
                except Exception as e:
                    print(f"Error researching {topic}: {str(e)}")
                    # Continue with other topics rather than failing completely

            # Step 3: Curate the content with separate preference content
            if state["research_results"]:
                print("Curating research results...")
                research_summary = {}
                for topic, results in state["research_results"].items():
                    answer = results.get("answer", "No answer provided")
                    sources = [f"Source: {r['title']}\nURL: {r['url']}\nContent: {r['content']}"
                               for r in results.get("results", [])]
                    research_summary[topic] = {
                        "answer": answer,
                        "sources": sources[:3]  # Limit to top 3 sources for brevity
                    }

                base_prompt = f"""
                You are a travel content curator. Based on the research results provided, organize the information into:
                1. Local Foods: Include traditional dishes, popular restaurants, food markets, and culinary experiences.
                2. Local Activities: Include attractions, experiences, tours, and unique things to do.

                For each category, provide:
                - 5-7 specific items with brief descriptions
                - Key details (location, what makes it special, etc.)
                """

                # Add preference instructions if needed
                if preferences:
                    preference_section = f"""
                    3. MOST IMPORTANT: Create a separate "preference_recommendations" category that ONLY contains 
                    information related to these specific user preferences: "{preferences}"

                    For the preference recommendations:
                    - Include at least 3-5 detailed items for EACH distinct preference
                    - Include practical information like how to get there, costs, best times to visit
                    - If a preference is outside the main destination, include transportation options, travel time, and day trip possibilities
                    - If any preference seems ambiguous or has multiple interpretations, provide recommendations for each interpretation
                    """
                    base_prompt += preference_section

                # Add output format instructions
                if preferences:
                    format_section = f"""
                    Research results:
                    {json.dumps(research_summary, indent=2)}

                    Format your response as JSON with three main keys: "foods", "activities", and "preference_recommendations".
                    Each should contain an array of objects with "name", "description", and additional fields as needed.
                    For preference_recommendations, include a "preference_category" field to indicate which specific preference it addresses.
                    """
                else:
                    format_section = f"""
                    Research results:
                    {json.dumps(research_summary, indent=2)}

                    Format your response as JSON with two main keys: "foods" and "activities".
                    Each should contain an array of objects with "name" and "description" fields.
                    """

                full_prompt = base_prompt + format_section

                response = self.openai.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.7
                )

                curated_content = json.loads(response.choices[0].message.content)
                state["curated_content"] = curated_content

                foods_count = len(curated_content.get("foods", []))
                activities_count = len(curated_content.get("activities", []))
                preference_count = len(curated_content.get("preference_recommendations", []))

                log_message = f"Research curated into {foods_count} food recommendations and {activities_count} activity recommendations"
                if preferences:
                    log_message += f" with {preference_count} preference-specific recommendations"

                state["messages"].append({
                    "role": "assistant",
                    "content": log_message
                })
                print(log_message)

            # Step 4: Create the final travel plan
            if state["curated_content"]:
                print("Creating final travel plan...")

                # Base prompt for both preference and non-preference cases
                base_prompt = f"""
                You are a travel planner for {destination}. Based on the curated research about local foods and activities,
                create a well-formatted travel guide section that highlights the unique culinary and activity experiences.

                Make your recommendations engaging, practical, and authentic to the local culture.
                """

                # Add preference-specific instructions if preferences exist
                if preferences:
                    preference_section = f"""
                    IMPORTANT: The traveler has these specific preferences: "{preferences}"

                    The final travel guide MUST include a prominent, dedicated section called "YOUR PREFERENCES" 
                    that focuses exclusively on the traveler's stated preferences. This section should:

                    1. Be placed prominently in the guide (after the introduction)
                    2. Begin with "Based on your specific interests in {preferences}, here are our tailored recommendations:"
                    3. Include comprehensive information about each preference
                    4. If a preference involves a location outside the main destination, include details about:
                       - How to get there (transportation options)
                       - How far it is (distance and travel time)
                       - Whether it works as a day trip or requires overnight stay
                       - Any special considerations for visiting
                    """
                    base_prompt += preference_section

                # Content and formatting instructions
                content_section = f"""
                Curated content:
                {json.dumps(state["curated_content"], indent=2)}
                """

                # Output format
                if preferences:
                    format_section = f"""
                    Format your response as JSON with keys:
                    - "title": A catchy title for this section
                    - "introduction": A brief introduction to the destination (acknowledging the traveler's preferences)
                    - "preference_section": The dedicated section addressing the user's specific interests
                    - "food_highlights": Formatted list of food recommendations as a string with bullet points (- item)
                    - "activity_highlights": Formatted list of activity recommendations as a string with bullet points (- item)
                    - "conclusion": A brief conclusion with tips for travelers
                    """
                else:
                    format_section = f"""
                    Format your response as JSON with keys:
                    - "title": A catchy title for this section
                    - "introduction": A brief introduction to the food and activity scene
                    - "food_highlights": Formatted list of food recommendations as a string with bullet points (- item)
                    - "activity_highlights": Formatted list of activity recommendations as a string with bullet points (- item)
                    - "conclusion": A brief conclusion with tips for travelers
                    """

                full_prompt = base_prompt + content_section + format_section

                response = self.openai.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[{"role": "system", "content": full_prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.7
                )

                final_plan = json.loads(response.choices[0].message.content)
                state["final_plan"] = final_plan

                state["messages"].append({
                    "role": "assistant",
                    "content": f"Travel guide section for {destination} has been created successfully!"
                })
                print(f"Travel plan created with title: {final_plan.get('title')}")

        except Exception as e:
            error_msg = f"Error in travel research process: {str(e)}"
            print(error_msg)
            state["error"] = error_msg
            import traceback
            traceback_str = traceback.format_exc()
            print(f"Detailed traceback: {traceback_str}")

        elapsed_time = time.time() - start_time
        print(f"=== Travel research completed in {elapsed_time:.1f} seconds ===")

        return state