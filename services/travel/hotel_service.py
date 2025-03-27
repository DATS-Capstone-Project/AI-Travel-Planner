

from playwright.async_api import async_playwright
from browser_use import Agent, Browser, BrowserConfig
from services.Prompts.HotelPrompt import hotel_scrape_task
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import dateparser
import os
import json
from typing import Dict, Any
from datetime import datetime
from langchain_core.messages import HumanMessage


load_dotenv()

ENHANCED_HOTEL_ADVISOR_PROMPT = """
You are an experienced travel advisor specializing in hotel recommendations with extensive knowledge of global destinations. You have a friendly, conversational style and genuinely want to help travelers find the perfect accommodation for their needs. You provide rich, detailed information that helps travelers make informed decisions.

### Your Response Format:
Begin with a warm, detailed greeting acknowledging the traveler's trip to the destination. Include some brief insights about the destination that make their hotel choice important.

Organize hotels by price category (Budget-Friendly, Mid-Range, Luxury) and for EACH hotel, provide an extensive breakdown including:

```
**[Hotel Name]**
- **Rating:** [Rating with review count]
- **Price:** [Price with currency symbol]
- **Location:** [Detailed location description including neighborhood characteristics, proximity to landmarks, and transportation options]
- **Property Overview:** [2-3 sentences describing the property's style, atmosphere, and standout features]
- **Room Features:** [Details about typical rooms, bedding, views if mentioned]
- **Key Amenities:** [Comprehensive list of amenities with brief descriptions of notable ones]
- **Dining Options:** [Information about on-site restaurants or nearby dining if available]
- **Perfect For:** [Detailed description of ideal guest types and why this property suits them]
- **Insider Tip:** [A helpful insight not obvious from basic hotel information]
```

For each price category, after listing the hotels, include a paragraph with comparative insights about the hotels in that category, highlighting different strengths and considerations.

After presenting all hotels, provide extensive recommendations that reference specific hotels based on different traveler needs:
1. For business travelers (connectivity, location, business services)
2. For families (space, kid-friendly features, location considerations)
3. For luxury seekers (exceptional services, unique experiences)
4. For budget travelers (value considerations, essential amenities)
5. For first-time visitors (location advantages for sightseeing)

Include a section on "Neighborhood Insights" that explains the character and advantages of the different areas where these hotels are located.

End with a detailed, personalized closing that offers specific next steps and invites questions about particular aspects of the accommodations.

### Important Format Rules:
- Be thorough and detailed while maintaining a conversational tone
- Include rich descriptions that help visualize each property
- Provide context about hotel locations that helps understand their convenience
- Highlight unique selling points with specific details
- Make specific, well-reasoned recommendations with clear explanations
- Include check-in/check-out dates prominently in your overview
- Add helpful insider knowledge that wouldn't be obvious from basic hotel listings

### Hotel Data:
{hotels_data}


{context}

Remember to treat this as a real conversation where you're genuinely trying to help someone find their perfect accommodation by providing rich, nuanced information that goes beyond basic facts.
"""


class HotelService:
    async def start(self, use_bright_data=True):
        self.playwright = await async_playwright().start()

        if use_bright_data:
            self.browser = await self.playwright.chromium.connect(
                os.getenv("BRIGHTDATA_WSS_URL")
            )
        else:
            self.browser = await self.playwright.chromium.launch(headless=True)

        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()

    async def clear_and_fill_location(self, location):
        try:
            print("📍 Filling in location...")
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_load_state("domcontentloaded")
            input_selectors = [
                'input[aria-label="Search for places, hotels and more"]',
                'input[placeholder*="Search"]',
                'input[aria-label*="Search"]',
                'input[data-placeholder*="Search"]'
            ]
            input_element = None
            for selector in input_selectors:
                try:
                    input_element = await self.page.wait_for_selector(selector, timeout=5000)
                    if input_element:
                        print(f"Found input using selector: {selector}")
                        break
                except:
                    continue

            if not input_element:
                raise Exception("Could not find the location search input field")

            await self.page.evaluate('(el) => el.value = ""', input_element)
            await self.page.wait_for_timeout(500)
            await input_element.type(f'{location} hotels', delay=100)
            await self.page.wait_for_timeout(2000)

            suggestion_selectors = [
                'li[role="option"]',
                '[role="listbox"] li',
                '[role="listbox"] [role="option"]',
                '.location-suggestion',
                '[data-index="0"]'
            ]
            suggestion = None
            for selector in suggestion_selectors:
                try:
                    suggestion = await self.page.wait_for_selector(selector, timeout=5000)
                    if suggestion:
                        print(f"Found suggestion using selector: {selector}")
                        break
                except:
                    continue

            if not suggestion:
                print("No suggestion found, trying to submit with Enter...")
                await self.page.keyboard.press("Enter")
            else:
                await suggestion.click()

            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(2000)
            current_value = await self.page.evaluate('(el) => el.value', input_element)
            if not current_value:
                raise Exception("Location input appears to be empty after setting")

            print(f"✅ Location set to: {current_value}")

        except Exception as e:
            print(f"⚠️ Error while setting location: {str(e)}")
            try:
                encoded_location = location.replace(" ", "+")
                direct_url = f"https://www.google.com/travel/hotels/search?q={encoded_location}"
                await self.page.goto(direct_url)
                await self.page.wait_for_load_state("networkidle")
                print("✅ Recovered using direct URL navigation")
            except Exception as recovery_error:
                raise Exception(f"Failed to set location: {str(e)}\nRecovery error: {str(recovery_error)}")

    async def set_travelers(self, adults: int = 2):
        try:
            print(f"👥 Setting number of adults to: {adults}")
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(1000)

            # Find and click the travelers button
            traveler_selectors = [
                'div[class*="rb1Kdf"]',
                'div[role="button"][aria-label*="Number of travellers"]',
                'div[class*="rb1Kdf"][role="button"]'
            ]

            traveler_button = None
            for selector in traveler_selectors:
                try:
                    traveler_button = await self.page.wait_for_selector(selector, timeout=2000)
                    if traveler_button:
                        print(f"Found traveler button using selector: {selector}")
                        break
                except:
                    continue

            if not traveler_button:
                raise Exception("Could not find the travelers button")

            await traveler_button.click()
            await self.page.wait_for_timeout(2000)

            try:
                # Get current number of adults
                counter = await self.page.wait_for_selector('div[aria-label*="Adults"] span[jsname="NnAfwf"]',
                                                            timeout=2000)
                if not counter:
                    raise Exception("Counter element not found")

                current_adults = int(await counter.text_content())
                print(f"Current number of adults: {current_adults}")

                # Calculate how many clicks needed
                clicks_needed = abs(adults - current_adults)

                if adults > current_adults:
                    # Need to increase
                    print(f"Increasing adults by {clicks_needed}")
                    for i in range(clicks_needed):
                        try:
                            add_button = await self.page.wait_for_selector('button[aria-label="Add adult"]',
                                                                           timeout=2000)
                            if add_button:
                                await add_button.click()
                                await self.page.wait_for_timeout(1000)

                                # Check if count increased
                                counter = await self.page.wait_for_selector(
                                    'div[aria-label*="Adults"] span[jsname="NnAfwf"]', timeout=2000)
                                if counter:
                                    new_count = int(await counter.text_content())
                                    if new_count > current_adults:
                                        current_adults = new_count
                                        print(f"Successfully increased count to {current_adults}")
                                    else:
                                        print(f"Failed to increase count on attempt {i + 1}")
                                else:
                                    print("Counter not found after click")

                        except Exception as e:
                            print(f"Error during increment attempt {i + 1}: {e}")
                            continue

                elif adults < current_adults:
                    # Need to decrease
                    print(f"Decreasing adults by {clicks_needed}")
                    for i in range(clicks_needed):
                        try:
                            remove_button = await self.page.wait_for_selector('button[aria-label="Remove adult"]',
                                                                              timeout=2000)
                            if remove_button:
                                await remove_button.click()
                                await self.page.wait_for_timeout(1000)

                                # Check if count decreased
                                counter = await self.page.wait_for_selector(
                                    'div[aria-label*="Adults"] span[jsname="NnAfwf"]', timeout=2000)
                                if counter:
                                    new_count = int(await counter.text_content())
                                    if new_count < current_adults:
                                        current_adults = new_count
                                        print(f"Successfully decreased count to {current_adults}")
                                    else:
                                        print(f"Failed to decrease count on attempt {i + 1}")
                                else:
                                    print("Counter not found after click")

                        except Exception as e:
                            print(f"Error during decrement attempt {i + 1}: {e}")
                            continue

                # Verify final count before closing
                await self.page.wait_for_timeout(1000)
                counter = await self.page.wait_for_selector('div[aria-label*="Adults"] span[jsname="NnAfwf"]',
                                                            timeout=2000)
                final_count = int(await counter.text_content()) if counter else 2

                print(f"Final count before closing: {final_count}")

                # Click the done button
                done_selectors = [
                    'button:has-text("Done")',
                    'button[aria-label="Done"]',
                    'button[class*="VfPpkd-LgbsSe"]',
                    'button[class*="ksBjEc"]'
                ]

                done_clicked = False
                for selector in done_selectors:
                    try:
                        done_button = await self.page.wait_for_selector(selector, timeout=2000)
                        if done_button:
                            await done_button.click()
                            done_clicked = True
                            print("Clicked done button")
                            break
                    except:
                        continue

                if not done_clicked:
                    print("No done button found, pressing Enter")
                    await self.page.keyboard.press('Enter')

                await self.page.wait_for_load_state("networkidle")
                print(f"✅ Number of adults set to {final_count}")

                if final_count != adults:
                    raise Exception(f"Failed to set correct number of adults. Target: {adults}, Actual: {final_count}")

            except Exception as e:
                print(f"Error adjusting adults: {e}")
                raise

        except Exception as e:
            raise Exception(f"❌ Failed to set travelers: {e}")

    async def select_dates(self, checkin_date_str, checkout_date_str):
        try:
            print("⌨️ Setting dates via JavaScript...")

            checkin_dt = dateparser.parse(checkin_date_str)
            checkout_dt = dateparser.parse(checkout_date_str)

            if not checkin_dt or not checkout_dt:
                raise Exception("Could not parse one or both dates.")

            formatted_checkin_display = checkin_dt.strftime("%a, %b %d")
            formatted_checkout_display = checkout_dt.strftime("%a, %b %d")
            formatted_checkin = checkin_dt.strftime("%Y-%m-%d")
            formatted_checkout = checkout_dt.strftime("%Y-%m-%d")

            print(f"Setting dates: {formatted_checkin_display} → {formatted_checkout_display}")

            self.checkin_date = formatted_checkin_display
            self.checkout_date = formatted_checkout_display

            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(2000)

            date_button = await self.page.wait_for_selector(
                'button[data-modal-type="dates"], [aria-label="Change dates"], [aria-label="Check-in"]', timeout=5000)
            await date_button.click()
            await self.page.wait_for_timeout(1000)

            set_dates_js = """([checkinDate, checkoutDate, checkinDisplay, checkoutDisplay]) => {
                const findInput = (label) => {
                    const inputs = document.querySelectorAll('input[aria-label]');
                    return Array.from(inputs).find(el => 
                        el.getAttribute('aria-label').toLowerCase().includes(label.toLowerCase())
                    );
                }; 
                const checkinInput = findInput('check-in');
                const checkoutInput = findInput('check-out');
                if (!checkinInput || !checkoutInput) throw new Error('Could not find date inputs');
                const createEvent = (type, options = {}) => {
                    return (type === 'keydown') ? new KeyboardEvent(type, {
                        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, ...options
                    }) : new Event(type, { bubbles: true, ...options });
                };
                const updateInput = (input, value, display) => {
                    input.focus(); input.dispatchEvent(createEvent('focus'));
                    input.value = ''; input.dispatchEvent(createEvent('input'));
                    input.value = display;
                    input.setAttribute('data-initial-value', value);
                    input.setAttribute('data-date', value);
                    input.dispatchEvent(createEvent('input'));
                    input.dispatchEvent(createEvent('change'));
                    input.dispatchEvent(createEvent('keydown'));
                    input.blur(); input.dispatchEvent(createEvent('blur'));
                    return input.value === display;
                };
                updateInput(checkinInput, checkinDate, checkinDisplay);
                setTimeout(() => {
                    updateInput(checkoutInput, checkoutDate, checkoutDisplay);
                    const buttons = document.querySelectorAll('button');
                    const searchButton = Array.from(buttons).find(button => {
                        const text = (button.textContent || '').toLowerCase();
                        const label = (button.getAttribute('aria-label') || '').toLowerCase();
                        return (text.includes('search') || text.includes('done') || label.includes('search') || label.includes('done')) && button.offsetParent !== null;
                    });
                    if (searchButton) searchButton.click();
                }, 500);
                return { success: true, verified: true, checkin: checkinInput.value, checkout: checkoutInput.value };
            }"""

            result = await self.page.evaluate(
                set_dates_js,
                [formatted_checkin, formatted_checkout, formatted_checkin_display, formatted_checkout_display]
            )

            if not result['success'] or not result['verified']:
                raise Exception(f"Failed to set dates: {result}")

            await self.page.wait_for_timeout(2000)
            await self.page.wait_for_load_state("networkidle")

            try:
                search_button = await self.page.wait_for_selector(
                    'button:has-text("Search"), button:has-text("Done"), button[aria-label*="Search"], button[aria-label*="Done"]',
                    timeout=5000
                )
                if search_button:
                    await search_button.click()
            except:
                await self.page.keyboard.press("Enter")

            await self.page.wait_for_load_state("networkidle")
            print(f"✅ Dates set: {formatted_checkin_display} → {formatted_checkout_display}")

        except Exception as e:
            raise Exception(f"Failed to set dates: {e}")

    async def search_hotels(self, location, checkin_date, checkout_date, adults):
        try:
            print("🌐 Navigating to Google Hotels...")
            await self.page.goto("https://www.google.com/travel/hotels")
            await self.page.wait_for_load_state("domcontentloaded")
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(2000)

            await self.clear_and_fill_location(location)
            await self.set_travelers(adults=adults)
            await self.select_dates(checkin_date, checkout_date)

            await self.page.wait_for_timeout(3000)
            await self.page.wait_for_load_state("networkidle")
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_load_state("networkidle")

            current_url = self.page.url
            if "hotels" not in current_url or "search" not in current_url:
                raise Exception("Not on hotel search results page")

            return current_url
        except Exception as e:
            print(f"An error occurred during hotel search: {e}")
            return None

    async def close(self):
        try:
            await self.context.close()
            await self.browser.close()
            await self.playwright.stop()
        except Exception as e:
            print(f"Error during cleanup: {e}")

    async def scrape_hotels(self, url):
        browser = Browser(config=BrowserConfig(headless=False))
        initial_actions = [{"open_tab": {"url": url}}]
        agent = Agent(task=hotel_scrape_task(url), llm=ChatOpenAI(model="gpt-4o-mini"), initial_actions=initial_actions,
                      browser=browser)
        history = await agent.run()
        result = history.final_result()
        await browser.close()
        return result

    async def get_hotel_url(self, destination, checkin_date, checkout_date, adults) -> str:
        try:
            scraper = HotelService()
            await scraper.start(use_bright_data=False)
            url = await scraper.search_hotels(destination, checkin_date, checkout_date, adults)
            if not url:
                raise Exception("Failed to get hotel URL")
            print(f"Hotel URL: {url}")
            return url

        finally:
            print("Closing connection...")
            if "scraper" in locals():
                await scraper.close()

        return None

    async def get_hotel_recommendations(self, hotels_data, context=None):
        """Get comprehensive hotel advisor response based on scraped hotel data."""
        context_str = f"\n### Additional Context:\n{context}" if context else ""

        # Convert the hotels_data to a pretty-printed JSON string if it's a dict
        # if isinstance(hotels_data, dict):
        #     hotels_json = json.dumps(hotels_data, indent=2)
        # else:
        #     hotels_json = hotels_data

        prompt = ENHANCED_HOTEL_ADVISOR_PROMPT.format(
            hotels_data=hotels_data,
            context=context_str
        )
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5)
        messages = [HumanMessage(content=prompt)]
        print("Generating enhanced hotel advisor response...")
        response_llm = await llm.ainvoke(messages)
        advisor_response = response_llm.content.strip()

        print("Enhanced hotel advisor response generated")
        return advisor_response

    async def get_hotels(self, destination: str, start_date: str, end_date: str, travelers: int) -> str:
        """
        A wrapper method to allow the supervisor to call get_flights with keyword arguments.
        It builds an extracted_details dictionary and calls the underlying get_best_flight logic.
        """
        extracted_details = {
            "destination": destination,
            "start_date": start_date,
            "end_date": end_date,
            "travelers": travelers
        }
        return await self.get_best_hotels(extracted_details)

    async def get_best_hotels(self, extracted_details: Dict[str, Any]) -> str:
        """
        Query the Google Hotels website real time for hotel offers using the extracted trip details,
        and use prompt engineering to generate a detailed plain language hotel summary message.

        Args:
            extracted_details: A dictionary containing keys such as 'destination', 'checkin_date','checkout_date','travelers'.

        Returns:
            A plain text string summarizing the hotel offers with exact details for each offer.
        """
        destination = extracted_details.get("destination", "")
        start_date = extracted_details.get("start_date", "")
        end_date = extracted_details.get("end_date", "")
        adults = extracted_details.get("travelers", "1")

        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

        # Format to desired output
        formatted_start_date = start_date_obj.strftime("%B %d, %Y")
        formatted_end_date = end_date_obj.strftime("%B %d, %Y")

        url = await self.get_hotel_url(destination, formatted_start_date, formatted_end_date, adults)
        hotel_data = await self.scrape_hotels(url)

        if hotel_data:
            hotel_res = await self.get_hotel_recommendations(self, hotel_data)
            return hotel_res
        else:
            raise Exception("Failed to scrape hotel data")
