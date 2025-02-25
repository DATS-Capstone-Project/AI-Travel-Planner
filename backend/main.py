from fastapi import FastAPI, HTTPException
from .models import ChatRequest, ChatResponse, TripDetails
from .state_manager import state_manager
from .agents import flight_agent, hotel_agent, activity_agent
from .utils import parse_date, validate_dates
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()


# OpenAI setup

def generate_prompt(session: dict) -> str:
    """Generate a prompt for OpenAI based on missing slots."""
    missing = []
    if not session["destination"]:
        missing.append("destination")
    if not session["start_date"]:
        missing.append("start date")
    if not session["end_date"]:
        missing.append("end date")
    if not session["travelers"]:
        missing.append("number of travelers")
    if missing:
        return f"The user is planning a trip. Ask for the following details: {', '.join(missing)}."
    return "All details are collected. Confirm the trip."


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session = state_manager.get_session(request.session_id)

    # Use OpenAI to handle the conversation
    prompt = generate_prompt(session)
    response = client.chat.completions.create(model="gpt-3.5-turbo-0125",
                                              messages=[
                                                  {"role": "system", "content": prompt},
                                                  {"role": "user", "content": request.message},
                                              ])
    bot_response = response.choices[0].message.content

    # Update session state based on user input
    if "destination" in request.message.lower():
        session["destination"] = request.message
    if "date" in request.message.lower():
        dates = [parse_date(d) for d in request.message.split() if parse_date(d)]
        if dates:
            session["start_date"] = dates[0]
            if len(dates) > 1:
                session["end_date"] = dates[1]

    # If all details are collected, generate itinerary
    if all(session.values()):
        if not validate_dates(session["start_date"], session["end_date"]):
            return ChatResponse(response="End date must be after start date. Please correct your dates.")

        flights = flight_agent.get_flights(session["destination"], session["start_date"], session["travelers"])
        hotels = hotel_agent.get_hotels(session["destination"], session["start_date"], session["end_date"],
                                        session["budget"])
        activities = activity_agent.get_activities(session["destination"], session["preferences"])
        itinerary = f"Here's your trip plan:\n✈️ {flights}\n🏨 {hotels}\n🎡 {activities}"
        return ChatResponse(response=itinerary)

    return ChatResponse(response=bot_response)
