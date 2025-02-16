from playwright.sync_api import sync_playwright, TimeoutError
import os
import requests
import time
import urllib.parse
import random
import logging
from base64 import b64encode
from user_agent import generate_user_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def send_telegram_message(message: str) -> dict:
    """
    使用bot API发送Telegram消息
    """
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id:
        logging.warning("Telegram bot token 或 chat ID 未配置，无法发送消息。")
        return {"ok": False, "description": "Telegram credentials not configured"}

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"发送Telegram消息时发生错误: {e}")
        return {"ok": False, "description": str(e)}

def wait_for_cloudflare(page, max_wait_time=60):
    """
    等待Cloudflare验证通过
    """
    start_time = time.time()
    while time.time() - start_time < max_wait_time:
        try:
            # 检查是否存在Cloudflare验证页面的特征
            if page.locator("h1:has-text('Just a moment')").count() > 0:
                logging.info("等待Cloudflare验证通过...")
                time.sleep(2)
                continue
                
            # 检查登录表单是否可见
            if page.locator("input[placeholder='Enter email']").is_visible():
                logging.info("Cloudflare验证已通过")
                return True
                
            # 等待页面加载完成
            page.wait_for_load_state("networkidle", timeout=5000)
            if page.url == "https://client.webhostmost.com/login":
                if page.locator("input[placeholder='Enter email']").is_visible():
                    logging.info("Cloudflare验证已通过")
                    return True
            
        except Exception as e:
            logging.debug(f"等待过程中的正常异常: {e}")
            time.sleep(2)
            continue
            
    logging.error("等待Cloudflare验证超时")
    return False

def attempt_single_login(email: str, password: str) -> tuple[bool, str]:
    """
    单次登录尝试
    """
    with sync_playwright() as p:
        try:
            browser = p.firefox.launch(
                headless=True,
                firefox_user_prefs={
                    "network.cookie.cookieBehavior": 0,
                    "network.http.max-connections": 256,
                    "network.http.max-persistent-connections-per-proxy": 16,
                    "network.http.max-persistent-connections-per-server": 8,
                }
            )

            # 设置浏览器上下文
            context_options = {
                "user_agent": generate_user_agent(navigator="firefox"),
                "viewport": {'width': 1920, 'height': 1080},
                "locale": "en-US",
                "timezone_id": "America/Los_Angeles",
            }

            # 处理代理设置
            proxy_urls_str = os.environ.get("PROXY_URLS")
            if proxy_urls_str:
                proxy_urls = [url.strip() for url in proxy_urls_str.split(';')]
                if proxy_urls:
                    selected_proxy_url = random.choice(proxy_urls)
                    try:
                        parsed_url = urllib.parse.urlparse(selected_proxy_url)
                        if parsed_url.scheme and parsed_url.netloc:
                            if parsed_url.username and parsed_url.password:
                                proxy_server = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                context_options["proxy"] = {
                                    "server": proxy_server,
                                    "username": parsed_url.username,
                                    "password": parsed_url.password
                                }
                                logging.info(f"使用代理服务器: {proxy_server}")
                    except Exception as e:
                        logging.error(f"代理URL解析错误: {e}")

            context = browser.new_context(**context_options)
            page = context.new_page()

            try:
                # 导航到登录页面
                logging.info("正在访问登录页面...")
                page.goto("https://client.webhostmost.com/login", timeout=30000)
                
                # 等待Cloudflare验证通过
                if not wait_for_cloudflare(page):
                    return False, "Cloudflare验证等待超时"
                
                # 确保页面完全加载
                page.wait_for_load_state("networkidle", timeout=10000)
                
                # 等待登录表单可操作
                logging.info("正在等待登录表单...")
                page.locator("input[placeholder='Enter email']").wait_for(state="visible", timeout=10000)
                time.sleep(2)  # 额外等待以确保表单完全可交互

                # 填写登录表单
                logging.info("正在填写登录信息...")
                page.get_by_placeholder("Enter email").fill(email)
                page.get_by_placeholder("Password").fill(password)
                page.get_by_role("button", name="Login").click()

                # 检查登录结果
                try:
                    page.locator(".MuiAlert-message").wait_for(timeout=5000)
                    error_message = page.locator(".MuiAlert-message").inner_text()
                    return False, f"登录失败: {error_message}"
                except TimeoutError:
                    try:
                        page.wait_for_url("https://client.webhostmost.com/clientarea.php", timeout=5000)
                        return True, "登录成功!"
                    except TimeoutError:
                        try:
                            page.locator("text=Welcome, ").wait_for(timeout=5000)
                            return True, "登录成功!"
                        except TimeoutError:
                            return False, "登录失败：无法检测登录状态"

            except TimeoutError as e:
                return False, f"登录超时：{str(e)}"
            except Exception as e:
                return False, f"登录过程发生错误: {str(e)}"
            finally:
                context.close()
                browser.close()

        except Exception as e:
            return False, f"浏览器操作失败: {str(e)}"

def login_webhost(email: str, password: str) -> str:
    """
    使用10次重试机制登录WebHost账户
    """
    logging.info(f"开始登录账户 {email}")
    
    for attempt in range(10):
        logging.info(f"第 {attempt + 1}/10 次尝试登录 {email}")
        success, message = attempt_single_login(email, password)
        
        if success:
            result = f"账户 {email} - {message}（第 {attempt + 1}/10 次尝试）"
            logging.info(result)
            return result
            
        logging.warning(f"账户 {email} 第 {attempt + 1}/10 次尝试失败：{message}")
        time.sleep(2)
    
    result = f"账户 {email} - 10次尝试均失败"
    logging.error(result)
    return result

def main():
    accounts = os.environ.get('WEBHOST', '').split()
    login_statuses = []

    if not accounts:
        error_message = "未配置任何账户，请设置 WEBHOST 环境变量"
        logging.warning(error_message)
        send_telegram_message(error_message)
        print(error_message)
        return

    for account in accounts:
        try:
            email, password = account.split(':')
        except ValueError:
            error_msg = f"账户格式错误，请使用 email:password 格式: {account}"
            logging.error(error_msg)
            login_statuses.append(error_msg)
            continue

        status = login_webhost(email, password)
        login_statuses.append(status)
        print(status)

    if login_statuses:
        message = "WEBHOST 登录状态：\n\n" + "\n".join(login_statuses)
        send_telegram_message(message)
        print("登录状态已发送到Telegram")
    else:
        error_message = "没有登录状态可报告"
        send_telegram_message(error_message)
        print(error_message)

if __name__ == "__main__":
    main()
