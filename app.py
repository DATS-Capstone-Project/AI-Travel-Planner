
import streamlit as st
import requests
import uuid
from datetime import datetime

# Configure API URL
API_URL = "http://127.0.0.1:8000"

# Page setup
st.set_page_config(
    page_title="AI Travel Planner",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for flex containers with icons (icon outside the bubble)
st.markdown("""
<style>
    /* Parent container for user messages (right-aligned with icon on the right) */
    .user-msg-container {
        display: flex;
        justify-content: flex-end;
        align-items: center;
        margin-bottom: 10px;
    }
    /* Parent container for assistant messages (left-aligned with icon on top) */
    .assistant-msg-container {
        display: flex;
        flex-direction: column;  /* Stack icon above the message bubble */
        align-items: flex-start;
        margin-bottom: 10px;
    }
    /* Chat bubble for user messages */
    .user-msg {
        display: inline-block;
        background-color: rgba(70, 130, 180, 0.2);
        padding: 10px 15px;
        border-radius: 10px;
        border-left: 4px solid #4682b4;
        text-align: right;
        max-width: 60%;
        word-wrap: break-word;
        white-space: pre-wrap;
        margin-right: 10px;  /* space between bubble and icon */
    }
    /* Chat bubble for assistant messages */
    .assistant-msg {
        display: inline-block;
        background-color: rgba(46, 139, 87, 0.2);
        padding: 10px 15px;
        border-radius: 10px;
        border-left: 4px solid #2e8b57;
        text-align: left;
        max-width: 60%;
        word-wrap: break-word;
        white-space: pre-wrap;
        margin-top: 5px;  /* space between icon and bubble */
    }
    /* Styling for icons */
    .user-icon, .assistant-icon {
        font-size: 24px;
    }
    .travel-title {
        font-size: 24px;
        font-weight: bold;
        display: flex;
        align-items: center;
    }
    .travel-emoji {
        font-size: 28px;
        margin-right: 10px;
    }
    /* Optional: Adjust chat input appearance */
    .stChatInput textarea {
        min-height: 50px !important;
        max-height: 200px !important;
        resize: vertical;
    }
</style>
""", unsafe_allow_html=True)


def chat_with_bot(session_id, message):
    """Send message to backend API and get response."""
    try:
        response = requests.post(
            f"{API_URL}/chat",
            json={"session_id": session_id, "message": message},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error communicating with the server: {str(e)}")
        return {"response": "Sorry, I'm having trouble connecting to the server. Please try again later."}


def reset_session(session_id):
    """Reset session on the backend."""
    try:
        requests.post(f"{API_URL}/reset/{session_id}")
        return True
    except:
        return False


def main():
    # Initialize session state if not already set
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "trip_details" not in st.session_state:
        st.session_state.trip_details = {}
    if "pending_message" not in st.session_state:
        st.session_state.pending_message = None

    # Sidebar: Display Trip Details
    with st.sidebar:
        st.markdown('<div class="travel-title"><span class="travel-emoji">✈️</span>Trip Details</div>',
                    unsafe_allow_html=True)
        st.write("As I understand them so far:")
        if st.session_state.trip_details:
            details = st.session_state.trip_details
            if details.get("destination"):
                st.markdown(f"**Destination:** {details['destination']}")
            if details.get("origin"):
                st.markdown(f"**Origin:** {details['origin']}")
            else:
                st.markdown("**Origin:** *Not provided (Required)*")
            if details.get("start_date") and details.get("end_date"):
                st.markdown(f"**Dates:** {details['start_date']} to {details['end_date']}")
            elif details.get("start_date"):
                st.markdown(f"**Start Date:** {details['start_date']}")
            if details.get("travelers"):
                st.markdown(f"**Travelers:** {details['travelers']}")
            if details.get("budget"):
                st.markdown(f"**Budget:** ${details['budget']}")
            if details.get("preferences"):
                st.markdown(f"**Preferences:** {details['preferences']}")
        else:
            st.info("No trip details yet. Start chatting to plan your trip!")
        st.divider()
        if st.button("Start New Trip"):
            reset_session(st.session_state.session_id)
            st.session_state.messages = []
            st.session_state.trip_details = {}
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()

    # Main Chat Area
    st.markdown('<div class="travel-title"><span class="travel-emoji">✈️</span>AI Travel Planner</div>',
                unsafe_allow_html=True)
    st.write("Your personal AI-powered travel assistant")

    # Display a welcome message if no messages have been sent yet
    if not st.session_state.messages:
        st.info("""
        👋 Hi there! I'm your AI travel planner. Tell me about your trip, and I'll help you organize it.
        Try saying something like:
        - "I want to visit Paris for a week in June"
        - "Planning a trip to Japan with my family of 4"
        - "Looking for beach activities in Bali"
        """)

    # Display chat messages with containers and icons
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(
                f'<div class="user-msg-container">'
                f'  <div class="user-msg">{msg["content"]}</div>'
                f'  <span class="user-icon">👤</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="assistant-msg-container">'
                f'  <span class="assistant-icon">🤖</span>'
                f'  <div class="assistant-msg">{msg["content"]}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    # Chat input area
    user_input = st.chat_input("What are your travel plans?")
    if user_input:
        # Set pending message flag and append the user message
        st.session_state.pending_message = user_input
        st.session_state.messages.append({"role": "user", "content": user_input})
        # Immediately re-run so that the user message is displayed
        st.rerun()

    # If there's a pending message, process it
    if st.session_state.pending_message is not None:
        with st.spinner("Planning your trip..."):
            response_data = chat_with_bot(st.session_state.session_id, st.session_state.pending_message)
            response_text = response_data.get("response", "Sorry, I couldn't process that request.")
            if "extracted_data" in response_data and response_data["extracted_data"]:
                st.session_state.trip_details = response_data["extracted_data"]
            st.session_state.messages.append({"role": "assistant", "content": response_text})
            st.session_state.pending_message = None
            st.rerun()


if __name__ == "__main__":
    main()
