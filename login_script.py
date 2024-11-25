from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import os
import requests
import logging
import time
import random
from typing import List, Tuple
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('webhost_login_checker.log')
    ]
)

# 美国主要城市及其经纬度
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

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_message(self, message: str) -> dict:
        """发送消息到Telegram"""
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
            logging.error(f"发送Telegram消息失败: {str(e)}")
            return {"error": str(e)}

class WebHostLoginChecker:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.login_url = "https://webhostmost.com/login"
        self.dashboard_url = "https://webhostmost.com/clientarea.php"
        
        # 移动设备配置
        self.mobile_devices = [
            "iPhone 12",
            "iPhone 13",
            "Pixel 5",
            "Samsung Galaxy S21",
            "iPhone 13 Pro Max"
        ]

    def get_random_location(self):
        """随机选择一个美国地理位置"""
        return random.choice(US_LOCATIONS)

    def get_mobile_device(self):
        """随机选择一个移动设备配置"""
        return random.choice(self.mobile_devices)

    def get_us_user_agent(self):
        """生成美国地区的User-Agent"""
        mobile_os_versions = {
            "iPhone": ["15_0", "15_1", "15_2", "16_0", "16_1"],
            "Pixel": ["12", "13"],
            "Samsung": ["11", "12", "13"]
        }
        
        os_version = random.choice(mobile_os_versions["iPhone"])  # 使用iPhone的UA
        return f"Mozilla/5.0 (iPhone; CPU iPhone OS {os_version} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def attempt_login(self, page, email: str, password: str, location: dict) -> str:
        """单次登录尝试"""
        try:
            # 访问登录页面
            page.goto(self.login_url, wait_until="networkidle")
            
            # 等待并填写登录表单
            page.wait_for_selector('input[placeholder="Enter email"]', timeout=5000)
            page.get_by_placeholder("Enter email").fill(email)
            page.get_by_placeholder("Password").fill(password)
            
            # 点击登录按钮并等待响应
            with page.expect_navigation(timeout=10000):
                page.get_by_role("button", name="Login").click()

            # 检查错误消息
            error_selector = '.MuiAlert-message'
            if page.is_visible(error_selector):
                error_text = page.locator(error_selector).inner_text()
                raise Exception(f"登录错误: {error_text}")

            # 验证是否成功到达仪表板
            if not page.url.startswith(self.dashboard_url):
                raise Exception("未能跳转到仪表板页面")

            return f"登录成功 (从 {location['city']}, {location['state']})"

        except PlaywrightTimeout as e:
            raise Exception(f"页面响应超时: {str(e)}")
        except Exception as e:
            raise Exception(f"登录失败: {str(e)}")

    def check_login(self, email: str, password: str) -> str:
        """使用美国地理位置检查登录"""
        device = self.get_mobile_device()
        location = self.get_random_location()
        user_agent = self.get_us_user_agent()
        
        logging.info(f"使用设备: {device}")
        logging.info(f"模拟位置: {location['city']}, {location['state']}")

        try:
            with sync_playwright() as p:
                # 配置浏览器
                browser = p.firefox.launch(headless=self.headless)
                
                # 创建上下文并配置设备
                context = browser.new_context(
                    **p.devices[device],
                    locale='en-US',
                    timezone_id=location['timezone'],
                    geolocation={
                        "latitude": location['latitude'],
                        "longitude": location['longitude']
                    },
                    permissions=['geolocation']
                )
                
                # 设置HTTP头
                context.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": user_agent
                })
                
                page = context.new_page()

                try:
                    retry_count = 0
                    last_error = None
                    
                    while retry_count < 3:
                        try:
                            result = self.attempt_login(page, email, password, location)
                            msg = f"✅ 账号 {email} ({device}): {result}"
                            logging.info(msg)
                            return msg
                        except Exception as e:
                            last_error = str(e)
                            retry_count += 1
                            if retry_count < 3:
                                wait_time = 4 * (2 ** (retry_count - 1))
                                logging.warning(f"第 {retry_count} 次尝试失败，等待 {wait_time} 秒后重试...")
                                time.sleep(wait_time)
                    
                    msg = f"❌ 账号 {email} ({device}): 重试3次后失败 - {last_error}"
                    logging.error(msg)
                    return msg

                finally:
                    browser.close()

        except Exception as e:
            msg = f"❌ 账号 {email}: 意外错误 - {str(e)}"
            logging.error(msg)
            return msg

def parse_accounts(accounts_str: str) -> List[Tuple[str, str]]:
    """解析账号字符串为列表"""
    if not accounts_str:
        return []
    return [tuple(account.split(':')) for account in accounts_str.split()]

def main():
    # 获取环境变量
    accounts_str = os.environ.get('WEBHOST', '')
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    # 验证环境变量
    if not all([accounts_str, bot_token, chat_id]):
        error_msg = "缺少必要的环境变量配置"
        logging.error(error_msg)
        return

    # 初始化组件
    telegram = TelegramNotifier(bot_token, chat_id)
    checker = WebHostLoginChecker(headless=True)
    accounts = parse_accounts(accounts_str)

    if not accounts:
        error_msg = "未配置任何账号"
        logging.warning(error_msg)
        telegram.send_message(error_msg)
        return

    # 检查所有账号登录状态
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    login_statuses = []
    
    for email, password in accounts:
        status = checker.check_login(email, password)
        login_statuses.append(status)

    # 发送报告到Telegram
    message = f"*WebHost登录状态检查*\n"
    message += f"_时间: {timestamp}_\n\n"
    message += "\n".join(login_statuses)
    
    result = telegram.send_message(message)
    if "error" in result:
        logging.error(f"发送Telegram通知失败: {result['error']}")
    else:
        logging.info("Telegram通知发送成功")

if __name__ == "__main__":
    main()
