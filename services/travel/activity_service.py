
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
        print(f"============================================================")

        # Run the research
        result = await self.research_destination(target_dest)

        if result.get("final_plan"):
            plan = result["final_plan"]

            print(f"============================================================")
            print(f"  RESEARCH COMPLETED SUCCESSFULLY")
            print(f"============================================================")

            # Save the travel guide
            # output_file = f"{target_dest}.json"
            # with open(output_file, 'w', encoding='utf-8') as f:
            #     json.dump(plan, f, indent=2)

            print(f"\nTravel Guide: {plan.get('title')}")
            print(f"\nIntroduction: {plan.get('introduction')[:100]}...")
            #print(f"\nResults saved to {output_file}")
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
    async def research_destination(self,destination: str) -> AgentState:
        """
        Direct implementation of the travel research workflow without LangGraph
        """
        print(f"=== Starting travel research for {destination} ===")
        start_time = time.time()

        # Initialize state
        state = AgentState(
            destination=destination,
            messages=[{"role": "assistant", "content": f"Starting travel research for {destination}..."}],
            research_topics=[],
            research_results={},
            curated_content={},
            final_plan={},
            error=None
        )

        try:
            # Step 1: Generate research topics
            print("Generating research topics...")
            prompt = f"""
            You are a travel research supervisor. For the destination {destination}, 
            identify the top 3 categories of information we need to research about local foods 
            and the top 3 categories about local activities.

            Format your response as a JSON object with a key "topics" that contains an array of strings, 
            each representing a specific research topic. Be specific with your topics to get useful search results.

            Example format: {{"topics": ["Traditional breakfast foods in Barcelona", "Street food markets in Barcelona", ...]}}
            """

            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.5
            )

            content = json.loads(response.choices[0].message.content)
            research_topics = content["topics"]
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

            # Step 3: Curate the content
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

                prompt = f"""
                You are a travel content curator. Based on the research results provided, organize the information into:
                1. Local Foods: Include traditional dishes, popular restaurants, food markets, and culinary experiences.
                2. Local Activities: Include attractions, experiences, tours, and unique things to do.

                For each category, provide:
                - 5-7 specific items with brief descriptions
                - Key details (location, what makes it special, etc.)

                Research results:
                {json.dumps(research_summary, indent=2)}

                Format your response as JSON with two main keys: "foods" and "activities".
                Each should contain an array of objects with "name" and "description" fields.
                """

                response = self.openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.7
                )

                curated_content = json.loads(response.choices[0].message.content)
                state["curated_content"] = curated_content

                foods_count = len(curated_content.get("foods", []))
                activities_count = len(curated_content.get("activities", []))

                state["messages"].append({
                    "role": "assistant",
                    "content": f"Research curated into {foods_count} food recommendations and {activities_count} activity recommendations."
                })
                print(f"Curation complete with {foods_count} foods and {activities_count} activities")

            # Step 4: Create the final travel plan
            if state["curated_content"]:
                print("Creating final travel plan...")
                prompt = f"""
                You are a travel planner for {destination}. Based on the curated research about local foods and activities,
                create a well-formatted travel guide section that highlights the unique culinary and activity experiences.

                Make your recommendations engaging, practical, and authentic to the local culture.

                Curated content:
                {json.dumps(state["curated_content"], indent=2)}

                Format your response as JSON with keys:
                - "title": A catchy title for this section
                - "introduction": A brief introduction to the food and activity scene
                - "food_highlights": Formatted list of food recommendations as a string with bullet points (- item)
                - "activity_highlights": Formatted list of activity recommendations as a string with bullet points (- item)
                - "conclusion": A brief conclusion with tips for travelers
                """

                response = self.openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": prompt}],
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

        elapsed_time = time.time() - start_time
        print(f"=== Travel research completed in {elapsed_time:.1f} seconds ===")

        return state
