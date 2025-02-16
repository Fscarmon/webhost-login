

# login_script.py
from playwright.sync_api import sync_playwright, TimeoutError, Page, Browser
import os
import requests
import time
from typing import Tuple
import urllib.parse
import random
import logging
from dotenv import load_dotenv
from base64 import b64encode
from PIL import Image
import pytesseract
from io import BytesIO
from user_agent import generate_user_agent
from playwright.sync_api import BrowserContext

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def send_telegram_message(message: str, screenshot_path: str = None, reply_markup=None) -> dict:
    """
    使用bot API发送Telegram消息，可以选择附带截图，并且可以包含内联键盘
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
        "parse_mode": "Markdown",
        "reply_markup": reply_markup
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()

        if screenshot_path:
            with open(screenshot_path, "rb") as f:
                screenshot_data = f.read()
            base64_image = b64encode(screenshot_data).decode('utf-8')
            send_photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            photo_payload = {
                "chat_id": chat_id,
                "photo": base64_image,
                "caption": "验证码截图"
            }
            headers = {"Content-Type": "application/json"}
            photo_response = requests.post(send_photo_url, json=photo_payload, headers=headers)
            photo_response.raise_for_status()
            logging.info("截图已发送到Telegram")

        return response.json()

    except requests.exceptions.RequestException as e:
        logging.error(f"发送Telegram消息失败: {e}")
        return {"ok": False, "description": str(e)}
    except Exception as e:
        logging.error(f"发送Telegram消息时发生意外错误: {e}")
        return {"ok": False, "description": str(e)}

def solve_cloudflare_challenge(page: Page) -> bool:
    """
    尝试解决 Cloudflare 人机验证
    """
    try:
        if page.locator("h1:has-text('Just a moment')").count() > 0:
            logging.warning("检测到 Cloudflare 验证页面 (Just a moment)。")
            screenshot_path = "cloudflare_challenge.png"
            page.screenshot(path=screenshot_path)
            message = "Cloudflare 人机验证 (Just a moment) 页面出现，可能需要手动解决。"
            send_telegram_message(message, screenshot_path)
            return False

        if page.locator("input[type='checkbox']").count() > 0:
            logging.warning("检测到 Cloudflare 人机验证 (I am human 复选框)。 尝试自动选择...")
            try:
                page.locator("input[type='checkbox']").scroll_into_view_if_needed()
            except Exception as e:
                logging.warning(f"滚动到复选框时发生错误: {e}")
                pass

            try:
                page.locator("input[type='checkbox']").wait_for(state="visible", timeout=10000)
                page.locator("input[type='checkbox']").click(timeout=5000)
                
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                    if page.url == "https://client.webhostmost.com/login":
                        logging.info("Cloudflare 人机验证 (复选框) 已自动解决。")
                        return True

                except TimeoutError:
                    logging.warning("点击复选框后，页面加载超时，可能需要手动解决。")
                    screenshot_path = "cloudflare_challenge.png"
                    page.screenshot(path=screenshot_path)
                    message = "Cloudflare 人机验证 (复选框) 自动选择后，页面加载超时，可能需要手动解决。"
                    send_telegram_message(message, screenshot_path)

                return True

            except Exception as e:
                logging.error(f"尝试自动选择复选框时发生错误: {e}")
                screenshot_path = "cloudflare_challenge.png"
                page.screenshot(path=screenshot_path)
                message = f"尝试自动选择复选框时发生错误: {e}。 可能需要手动解决。"
                send_telegram_message(message, screenshot_path)

        logging.debug("未检测到 Cloudflare 挑战，或已自动通过。")
        return True

    except Exception as e:
        logging.error(f"解决 Cloudflare 验证码时发生错误: {e}")
        return False

def attempt_login(context: BrowserContext, email: str, password: str) -> Tuple[bool, str]:
    """
    尝试登录WebHost账户
    """
    logging.info(f"尝试登录账户: {email}")
    try:
        page = context.new_page()

        try:
            page.goto("https://client.webhostmost.com/login", timeout=20000)
        except TimeoutError as e:
            logging.error(f"导航到登录页面超时: {e}")
            return False, f"登录失败：导航超时"

        solve_cloudflare_challenge(page)

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except TimeoutError as e:
            logging.error(f"页面加载超时: {e}")
            return False, "登录失败: 页面加载超时"

        page.get_by_placeholder("Enter email").click()
        page.get_by_placeholder("Enter email").fill(email)
        page.get_by_placeholder("Password").click()
        page.get_by_placeholder("Password").fill(password)
        page.get_by_role("button", name="Login").click()

        try:
            page.locator(".MuiAlert-message").wait_for(timeout=5000)
            error_message = page.locator(".MuiAlert-message").inner_text()
            logging.warning(f"登录失败: {error_message}")
            return False, f"登录失败: {error_message}"
        except TimeoutError:
            try:
                page.wait_for_url("https://client.webhostmost.com/clientarea.php", timeout=5000)
                logging.info("登录成功!")
                return True, "登录成功!"
            except TimeoutError:
                try:
                    page.locator("text=Welcome, ").wait_for(timeout=5000)
                    logging.info("登录成功!")
                    return True, "登录成功!"
                except TimeoutError:
                    return False, "登录失败：无法检测登录状态"
        finally:
            page.close()

    except TimeoutError as e:
        return False, f"登录超时：{str(e)}"
    except Exception as e:
        return False, f"登录失败: {str(e)}"

def login_webhost(email: str, password: str, max_retries: int = 5) -> str:
    """
    使用重试机制登录WebHost账户
    """
    logging.info(f"开始登录账户 {email}, 最大重试次数: {max_retries}")
    proxy_urls_str = os.environ.get("PROXY_URLS")

    with sync_playwright() as p:
        browser = p.firefox.launch(
            headless=True,
            firefox_user_prefs={
                "network.cookie.cookieBehavior": 0,
                "network.http.max-connections": 256,
                "network.http.max-persistent-connections-per-proxy": 16,
                "network.http.max-persistent-connections-per-server": 8,
            }
        )

        for attempt in range(max_retries):
            try:
                context_options = {
                    "user_agent": generate_user_agent(navigator="firefox"),
                    "viewport": {'width': 1920, 'height': 1080},
                    "locale": "en-US",
                    "timezone_id": "America/Los_Angeles",
                }

                # 处理代理设置
                if proxy_urls_str:
                    proxy_urls = [url.strip() for url in proxy_urls_str.split(';')]
                    if proxy_urls:
                        selected_proxy_url = random.choice(proxy_urls)
                        logging.info(f"使用随机选择的代理: {selected_proxy_url}")
                        try:
                            parsed_url = urllib.parse.urlparse(selected_proxy_url)
                            if parsed_url.scheme and parsed_url.netloc:
                                if parsed_url.username is not None and parsed_url.password is not None:
                                    proxy_server = f"{parsed_url.scheme}://{parsed_url.netloc}"
                                    proxy_username = parsed_url.username
                                    proxy_password = parsed_url.password
                                    context_options["proxy"] = {
                                        "server": proxy_server,
                                        "username": proxy_username,
                                        "password": proxy_password
                                    }
                                    logging.info(f"使用代理服务器: {proxy_server}")
                                else:
                                    logging.warning(f"代理URL格式错误，缺少用户名或密码: {selected_proxy_url}")
                            else:
                                logging.warning(f"代理URL格式错误: {selected_proxy_url}")
                        except Exception as e:
                            logging.error(f"代理URL解析错误: {e}")
                else:
                    logging.info("未配置代理服务器, 将使用无代理连接")

                context = browser.new_context(**context_options)
                success, message = attempt_login(context, email, password)

                if success:
                    logging.info(f"账户 {email} 登录成功（第 {attempt + 1}/{max_retries} 次尝试）")
                    return f"账户 {email} - {message}（第 {attempt + 1}/{max_retries} 次尝试）"
                else:
                    logging.warning(f"账户 {email} 的第 {attempt + 1}/{max_retries} 次重试：{message}")
                    time.sleep(2 * (attempt + 1))

            except Exception as e:
                logging.error(f"账户 {email} 在第 {attempt + 1} 次尝试时发生错误: {e}")
                if attempt == max_retries - 1:
                    logging.error(f"账户 {email} - {max_retries} 次尝试后发生致命错误：{str(e)}")
                    return f"账户 {email} - {max_retries} 次尝试后发生致命错误：{str(e)}"
            finally:
                try:
                    if 'context' in locals():
                        context.close()
                        logging.debug("浏览器上下文已关闭")
                except Exception as e:
                    logging.error(f"关闭浏览器上下文时发生错误: {e}")

        browser.close()
        return f"账户 {email} - 所有 {max_retries} 次尝试均失败。"

def main():
    # 从环境变量获取账户信息
    accounts = os.environ.get('WEBHOST', '').split()
    login_statuses = []

    if not accounts:
        logging.warning("未配置任何账户，请设置 WEBHOST 环境变量")
        error_message = "未配置任何账户"
        send_telegram_message(error_message)
        print(error_message)
        return

    for account in accounts:
        try:
            email, password = account.split(':')
        except ValueError:
            logging.error(f"账户格式错误，请使用 email:password 格式: {account}")
            login_statuses.append(f"账户 {account} 格式错误")
            continue

        status = login_webhost(email, password)
        login_statuses.append(status)
        print(status)

    if login_statuses:
        message = "WEBHOST 登录状态：\n\n" + "\n".join(login_statuses)
        result = send_telegram_message(message)
        logging.info("消息已发送到Telegram: %s", result)
        print("消息已发送到Telegram：", result)
    else:
        error_message = "没有登录状态"
        send_telegram_message(error_message)
        print(error_message)

if __name__ == "__main__":
    main()

