from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import os
import requests
import logging
import time
import random
from typing import List, Tuple
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('webhost_login_checker.log')
    ]
)

# US locations with timezones
US_LOCATIONS = [
    {
        "city": "New York",
        "state": "NY",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "timezone": "America/New_York"
    },
    {
        "city": "Los Angeles",
        "state": "CA",
        "latitude": 34.0522,
        "longitude": -118.2437,
        "timezone": "America/Los_Angeles"
    },
    {
        "city": "Chicago",
        "state": "IL",
        "latitude": 41.8781,
        "longitude": -87.6298,
        "timezone": "America/Chicago"
    },
    {
        "city": "Houston",
        "state": "TX",
        "latitude": 29.7604,
        "longitude": -95.3698,
        "timezone": "America/Chicago"
    },
    {
        "city": "Phoenix",
        "state": "AZ",
        "latitude": 33.4484,
        "longitude": -112.0740,
        "timezone": "America/Phoenix"
    }
]

# Desktop browser configurations
DESKTOP_CONFIGS = [
    {
        "os": "Windows",
        "chrome_version": "119.0.0.0",
        "platform": "Windows NT 10.0; Win64; x64",
        "resolution": {"width": 1920, "height": 1080}
    },
    {
        "os": "macOS",
        "chrome_version": "119.0.0.0", 
        "platform": "Macintosh; Intel Mac OS X 10_15_7",
        "resolution": {"width": 1680, "height": 1050}
    },
    {
        "os": "Windows",
        "chrome_version": "118.0.0.0",
        "platform": "Windows NT 10.0; Win64; x64",
        "resolution": {"width": 1366, "height": 768}
    }
]

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_message(self, message: str) -> dict:
        """Send message to Telegram"""
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(self.base_url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to send Telegram message: {str(e)}")
            return {"error": str(e)}

class WebHostLoginChecker:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.login_url = "https://webhostmost.com/login"
        self.dashboard_url = "https://webhostmost.com/clientarea.php"

    def get_random_location(self):
        """Get a random US location"""
        return random.choice(US_LOCATIONS)

    def get_random_desktop_config(self):
        """Get a random desktop configuration"""
        config = random.choice(DESKTOP_CONFIGS)
        return {
            "user_agent": f"Mozilla/5.0 ({config['platform']}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{config['chrome_version']} Safari/537.36",
            "viewport": config["resolution"],
            "os": config["os"]
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def attempt_login(self, page, email: str, password: str, location: dict, desktop_info: dict) -> str:
        """Single login attempt"""
        try:
            # Navigate to login page
            page.goto(self.login_url, wait_until="networkidle")
            
            # Wait for and fill login form
            page.wait_for_selector('input[placeholder="Enter email"]', timeout=5000)
            page.get_by_placeholder("Enter email").fill(email)
            page.get_by_placeholder("Password").fill(password)
            
            # Click login button and wait for navigation
            with page.expect_navigation(timeout=10000):
                page.get_by_role("button", name="Login").click()

            # Check for error messages
            error_selector = '.MuiAlert-message'
            if page.is_visible(error_selector):
                error_text = page.locator(error_selector).inner_text()
                raise Exception(f"Login error: {error_text}")

            # Verify successful dashboard navigation
            if not page.url.startswith(self.dashboard_url):
                raise Exception("Failed to reach dashboard page")

            return f"Login successful (from {location['city']}, {location['state']} using {desktop_info['os']})"

        except PlaywrightTimeout as e:
            raise Exception(f"Page response timeout: {str(e)}")
        except Exception as e:
            raise Exception(f"Login failed: {str(e)}")

    def check_login(self, email: str, password: str) -> str:
        """Check login using desktop browser with US geolocation"""
        location = self.get_random_location()
        desktop_config = self.get_random_desktop_config()
        
        logging.info(f"Using {desktop_config['os']} from {location['city']}, {location['state']}")

        try:
            with sync_playwright() as p:
                # Launch browser (using Chromium for better compatibility)
                browser = p.chromium.launch(headless=self.headless)
                
                # Create context with desktop configuration
                context = browser.new_context(
                    locale='en-US',
                    timezone_id=location['timezone'],
                    geolocation={
                        "latitude": location['latitude'],
                        "longitude": location['longitude']
                    },
                    permissions=['geolocation'],
                    user_agent=desktop_config['user_agent'],
                    viewport=desktop_config['viewport']
                )
                
                page = context.new_page()

                try:
                    retry_count = 0
                    last_error = None
                    
                    while retry_count < 3:
                        try:
                            result = self.attempt_login(page, email, password, location, desktop_config)
                            msg = f"✅ Account {email}: {result}"
                            logging.info(msg)
                            return msg
                        except Exception as e:
                            last_error = str(e)
                            retry_count += 1
                            if retry_count < 3:
                                wait_time = 4 * (2 ** (retry_count - 1))
                                logging.warning(f"Attempt {retry_count} failed, waiting {wait_time} seconds before retry...")
                                time.sleep(wait_time)
                    
                    msg = f"❌ Account {email}: Failed after 3 retries - {last_error}"
                    logging.error(msg)
                    return msg

                finally:
                    browser.close()

        except Exception as e:
            msg = f"❌ Account {email}: Unexpected error - {str(e)}"
            logging.error(msg)
            return msg

def parse_accounts(accounts_str: str) -> List[Tuple[str, str]]:
    """Parse accounts string into list"""
    if not accounts_str:
        return []
    return [tuple(account.split(':')) for account in accounts_str.split()]

def main():
    # Get environment variables
    accounts_str = os.environ.get('WEBHOST', '')
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    # Validate environment variables
    if not all([accounts_str, bot_token, chat_id]):
        error_msg = "Missing required environment variables"
        logging.error(error_msg)
        return

    # Initialize components
    telegram = TelegramNotifier(bot_token, chat_id)
    checker = WebHostLoginChecker(headless=True)
    accounts = parse_accounts(accounts_str)

    if not accounts:
        error_msg = "No accounts configured"
        logging.warning(error_msg)
        telegram.send_message(error_msg)
        return

    # Check all account logins
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    login_statuses = []
    
    for email, password in accounts:
        status = checker.check_login(email, password)
        login_statuses.append(status)
        # Add random delay between checks
        if email != accounts[-1][0]:  # Don't delay after last account
            delay = random.uniform(3, 8)
            time.sleep(delay)

    # Send report to Telegram
    message = f"*WebHost Login Status Check*\n"
    message += f"_Time: {timestamp}_\n\n"
    message += "\n".join(login_statuses)
    
    result = telegram.send_message(message)
    if "error" in result:
        logging.error(f"Failed to send Telegram notification: {result['error']}")
    else:
        logging.info("Telegram notification sent successfully")

if __name__ == "__main__":
    main()
