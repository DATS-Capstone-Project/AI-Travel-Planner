import streamlit as st
import requests

BACKEND_URL = "http://127.0.0.1:8000"


def chat_with_bot(session_id: str, message: str) -> str:
    try:
        response = requests.post(
            f"{BACKEND_URL}/chat",
            json={"session_id": session_id, "message": message},
            timeout=7
        )
        response.raise_for_status()
        return response.json()["response"]
    except requests.exceptions.Timeout:
        return "Our servers are busy. Please try again in a moment."
    except requests.exceptions.RequestException:
        return "Connection error. Please check your internet connection."
    except Exception:
        return "Something went wrong. Please try again."


def main():
    st.title("🌍 AI Travel Planner")

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"session_{hash(id(st.session_state))}"

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # User input
    if prompt := st.chat_input("Where would you like to go?"):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Get bot response
        with st.spinner("Planning your trip..."):
            response = chat_with_bot(st.session_state.session_id, prompt)

        # Add bot response
        st.session_state.messages.append({"role": "assistant", "content": response})

        # Rerun to update UI
        st.rerun()


if __name__ == "__main__":
    main()