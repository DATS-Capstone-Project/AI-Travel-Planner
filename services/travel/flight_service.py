# services/travel/flight_service.py

import os
import logging
from typing import Dict, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from playwright.async_api import async_playwright
from browser_use import Agent, Browser, BrowserConfig
from services.Prompts.FlightsPrompt import flight_scrape_task
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)


class FlightService:
    """Service for handling flight-related operations using Amadeus API with integrated prompt engineering for flight selection."""

    def __init__(self):
        """
        Initialize the Amadeus client and the LLM client using environment variables.
        """
        self.llm = ChatOpenAI(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-3.5-turbo", temperature=0)

    async def start(self, use_bright_data=True):
        self.playwright = await async_playwright().start()

        if use_bright_data:
            # Bright Data configuration
            self.browser = await self.playwright.chromium.connect(
                os.getenv("BRIGHTDATA_WSS_URL")
            )
        else:
            # Local browser configuration
            self.browser = await self.playwright.chromium.launch(
                headless=True,  # Set to True for headless mode
            )

        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

    async def fill_and_select_airport(self, input_selector, airport_name):
        try:
            if input_selector == 'input[aria-label="Where to? "]':
                input_element = await self.page.wait_for_selector(input_selector)
                await input_element.type(airport_name, delay=200)
                await self.page.wait_for_selector(
                    f'li[role="option"][aria-label*="{airport_name}"]', timeout=8000
                )
                await self.page.wait_for_timeout(500)
            else:
                input_element = await self.page.wait_for_selector(input_selector)
                await self.page.evaluate('(el) => el.value = ""', input_element)
                await input_element.type(airport_name, delay=200)
                await self.page.wait_for_selector(
                    f'li[role="option"][aria-label*="{airport_name}"]', timeout=8000
                )
                await self.page.wait_for_timeout(500)

            # Try different selectors for the dropdown item
            dropdown_selectors = [
                f'li[role="option"][aria-label*="{airport_name}"]',
                f'li[role="option"] .zsRT0d:text-is("{airport_name}")',
                f'.zsRT0d:has-text("{airport_name}")',
            ]

            for selector in dropdown_selectors:
                try:
                    dropdown_item = await self.page.wait_for_selector(
                        selector, timeout=8000
                    )
                    if dropdown_item:
                        await dropdown_item.click()
                        await self.page.wait_for_load_state("networkidle")
                        return True
                except:
                    continue

            raise Exception(f"Could not select airport: {airport_name}")

        except Exception as e:
            print(f"Error filling airport: {str(e)}")
            await self.page.screenshot(path=f"error_{airport_name.lower()}.png")
            return False

    async def fill_flight_search(self, origin, destination, start_date, travelers):
        try:
            print("Navigating to Google Flights...")
            await self.page.goto("https://www.google.com/travel/flights")

            print("Filling in destination...")
            if not await self.fill_and_select_airport(
                    'input[aria-label="Where to? "]', destination
            ):
                raise Exception("Failed to set destination airport")

            print("Filling in origin...")
            if not await self.fill_and_select_airport(
                    'input[aria-label="Where from?"]', origin
            ):
                raise Exception("Failed to set origin airport")

            print("Setting number of travelers...")

            # Click the travelers button
            for i in range(int(travelers)):
                try:
                    await self.page.wait_for_selector('[aria-label="1 passenger"]', timeout=8000)
                    await self.page.click('[aria-label="1 passenger"]')
                    await self.page.wait_for_timeout(1000)
                    await self.page.wait_for_selector('[aria-label="Add adult"]', timeout=8000)
                    await self.page.click('[aria-label="Add adult"]')
                    await self.page.wait_for_timeout(1000)
                    done_button = await self.page.wait_for_selector(
                        'button[class="VfPpkd-LgbsSe ksBjEc lKxP2d LQeN7 bRx3h sIWnMc"]', timeout=5000
                    )
                    await done_button.click()
                except:
                    continue

            # Change the travelling type to "One Way"
            await self.page.click('div[role="combobox"][aria-haspopup="listbox"]')
            await self.page.wait_for_timeout(1000)
            await self.page.click('li[data-value="2"]')
            await self.page.wait_for_timeout(1000)

            print("Selecting dates...")
            # Click the departure date button
            await self.page.click('input[aria-label*="Departure"]')
            await self.page.wait_for_timeout(1000)

            # Select departure date
            departure_button = await self.page.wait_for_selector(
                f'div[aria-label*="{start_date}"]', timeout=8000
            )
            await departure_button.click()
            await self.page.wait_for_timeout(1000)

            # Click Done button if it exists
            try:
                done_button = await self.page.wait_for_selector(
                    'button[aria-label*="Done."]', timeout=5000
                )
                await done_button.click()
            except:
                print("No Done button found, continuing...")

            return self.page.url

        except Exception as e:
            print(f"An error occurred: {str(e)}")
            return None

    async def close(self):
        try:
            await self.context.close()
            await self.browser.close()
            await self.playwright.stop()
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")

    async def get_best_flight(self, extracted_details: Dict[str, Any]) -> str:
        """
        Query the Google Flight website real time for flight offers using the extracted trip details,
        compute key metrics (cheapest, fewest layovers, shortest duration, best options per cabin if available),
        and use prompt engineering to generate a detailed plain language flight summary message.
        
        Args:
            extracted_details: A dictionary containing keys such as 'origin', 'destination', 'start_date', 'travelers'.
                               
        Returns:
            A plain text string summarizing the flight offers with exact details for each offer.
        """
        origin = extracted_details.get("origin", "")
        destination = extracted_details.get("destination", "")
        start_date = extracted_details.get("start_date", "")
        end_date = extracted_details.get("end_date", "")
        travelers = extracted_details.get("travelers", 1)

        # Get the flight search URL
        try:
            scraper = FlightService()
            await scraper.start(use_bright_data=False)
            departing_flight_url = await scraper.fill_flight_search(
                origin=origin,
                destination=destination,
                start_date=start_date,
                travelers=travelers
            )

            returning_flight_url = await scraper.fill_flight_search(origin=destination,
                                                                    destination=origin,
                                                                    start_date=end_date,
                                                                    travelers=travelers
                                                                    )
        finally:
            print("Closing connection...")
            if "scraper" in locals():
                await scraper.close()

        if not departing_flight_url and not returning_flight_url:
            logger.error("Failed to retrieve flight search URL.")
            return "Unable to find flight offers at this time."

        departing_flight_result = await self.scrape_flights(departing_flight_url)
        returning_flight_result = await self.scrape_flights(returning_flight_url)

        logger.info(f"Processed flight offers JSON: {departing_flight_result, returning_flight_result}")

        prompt = (
            "You are a seasoned flight advisor with expertise in flight planning, advising, and booking"
            "Given the following JSON data of Departing and Returning flight offers, Generate a detailed plain text summary, Give adivce on the best options to choose from while listing all the options available.\n"
            "In the JSON, Each and every flight, include:\n"
            " - Departure date & time (local)" 
            " - Arrival date & time (local)"
            " - Origin & destination airports (Airport full names, ex: 'Los Angeles International Airport') "
            " - Full flight duration (in 'Xh Ym' format)"  
            " - Number of stops (integer)" 
            " - Layover airports & layover durations"
            " - Airline(s) (e.g. “Frontier”)"
            " - Individual leg prices (numeric only) if given separately"
            " - For each flight segment, include the carrier (as the full name with the code in parentheses)"
            "Here is the Departing flight JSON data:\n\n"
            f"{departing_flight_url}\n\n"
            "Here is the Returning flight JSON data:\n\n"
            f"{returning_flight_url}\n\n"
            "Return your answer as a clear plain text message."
        )

        messages = [HumanMessage(content=prompt)]
        response_llm = await self.llm.ainvoke(messages)
        human_message = response_llm.content.strip()
        logger.info(f"LLM generated human message: {human_message}")

        return human_message

    async def scrape_flights(self, url):
        browser = Browser(
            config=BrowserConfig(
                headless=False
            )
        )
        initial_actions = [
            {"open_tab": {"url": url}},
        ]

        agent = Agent(
            task=flight_scrape_task(url, "I want flights with price under 1000 USD"),
            llm=ChatOpenAI(model="gpt-4o-mini"),
            initial_actions=initial_actions,
            browser=browser,
        )

        history = await agent.run()
        await browser.close()
        result = history.final_result()
        return result

    async def get_flights(self, origin: str, destination: str, start_date: str, end_date: str,
                          travelers: int) -> str:
        """
        A wrapper method to allow the supervisor to call get_flights with keyword arguments.
        It builds an extracted_details dictionary and calls the underlying get_best_flight logic.
        """
        extracted_details = {
            "origin": origin,
            "destination": destination,
            "start_date": start_date,
            "end_date": end_date,
            "travelers": travelers
        }
        return await self.get_best_flight(extracted_details)
