from playwright.sync_api import sync_playwright, TimeoutError, Page, Browser
import os
import requests
import time
from typing import Tuple
import urllib.parse
import random
import logging
from dotenv import load_dotenv
from base64 import b64encode  # 用于截图的base64编码
from PIL import Image  #  图像处理
import pytesseract  # OCR  (需要安装 Tesseract OCR 引擎和 pytesseract 库)
from io import BytesIO
from user_agent import generate_user_agent  #  用于生成 User-Agent
from playwright.sync_api import BrowserContext # 导入 BrowserContext

# 加载 .env 文件中的环境变量 (如果存在)
load_dotenv()

# 配置日志记录 (与之前相同)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    # filename="login_script.log",
    # filemode="w"
)

#  ... send_telegram_message 函数 (与之前相同) ...
def send_telegram_message(message: str, screenshot_path: str = None, reply_markup=None) -> dict:  #  添加 reply_markup 参数
    """
    使用bot API发送Telegram消息，可以选择附带截图，并且可以包含内联键盘 (reply_markup)
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
        "reply_markup": reply_markup  #  添加 reply_markup 到 payload 中
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()  # 检查HTTP错误

        if screenshot_path:
            # 如果有截图，也发送截图
            with open(screenshot_path, "rb") as f:
                screenshot_data = f.read()
            # base64编码
            base64_image = b64encode(screenshot_data).decode('utf-8')
            send_photo_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            photo_payload = {
                "chat_id": chat_id,
                "photo": base64_image,  # 直接发送base64编码的图片
                "caption": "验证码截图"
            }
            headers = {"Content-Type": "application/json"}  # 设置Content-Type为application/json
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
    尝试解决 Cloudflare 人机验证。 包含自动处理和半自动的 Telegram 交互。
    专为处理 “I am human” 复选框设计.
    """
    try:
        # 1. 检查是否出现了 Cloudflare 验证页面 (Just a moment) - 仍然保留，以防万一
        if page.locator("h1:has-text('Just a moment')").count() > 0:
            logging.warning("检测到 Cloudflare 验证页面 (Just a moment)。")
            screenshot_path = "cloudflare_challenge.png"
            page.screenshot(path=screenshot_path)
            message = "Cloudflare 人机验证 (Just a moment) 页面出现，可能需要手动解决。请查看截图，手动解决后，手动重新运行脚本。"
            send_telegram_message(message, screenshot_path)
            return False  # 立即返回，需要用户手动解决，并重新运行脚本

        # 2. 检查是否存在 “I am human” 复选框，尝试自动选择
        if page.locator("input[type='checkbox']").count() > 0:  #  使用通用的复选框选择器
            logging.warning("检测到 Cloudflare 人机验证 (I am human 复选框)。 尝试自动选择...")
            #  2.1 尝试滚动到复选框 (如果需要)
            try:
                page.locator("input[type='checkbox']").scroll_into_view_if_needed()
            except Exception as e:
                logging.warning(f"滚动到复选框时发生错误: {e}")
                pass
            try:
                #  2.2 等待复选框可见
                page.locator("input[type='checkbox']").wait_for(state="visible", timeout=10000)
                #  2.3 尝试点击 "I am human" 复选框 (使用通用选择器)
                page.locator("input[type='checkbox']").click(timeout=5000)
                #  等待复选框被选中，并处理可能的后续页面变化。
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)  # 等待页面加载完毕， 增加超时时间
                    if page.url == "https://client.webhostmost.com/login":  # 重定向到登录页面，说明解决了
                        logging.info("Cloudflare 人机验证 (复选框) 已自动解决。")
                        return True

                except TimeoutError:
                    logging.warning("点击复选框后，页面加载超时，可能需要手动解决。")
                    screenshot_path = "cloudflare_challenge.png"
                    page.screenshot(path=screenshot_path)
                    message = "Cloudflare 人机验证 (复选框)  自动选择后，页面加载超时，可能需要手动解决。 请查看截图，手动解决后，重新运行脚本。"
                    send_telegram_message(message, screenshot_path)
                    # 自动点击失败，但是不返回False，而是继续。

                logging.info("Cloudflare 人机验证 (复选框) 已自动解决。")
                return True # 复选框点击成功，并且页面状态检测也成功

            except Exception as e:
                logging.error(f"尝试自动选择复选框时发生错误: {e}")
                screenshot_path = "cloudflare_challenge.png"
                page.screenshot(path=screenshot_path)
                message = f"尝试自动选择复选框时发生错误: {e}。  可能需要手动解决。 请查看截图，手动解决后，重新运行脚本。"
                send_telegram_message(message, screenshot_path)
                # 自动点击失败，但是不返回False，而是继续。

        # 3.  如果以上都没有检测到，也认为没有验证码，直接返回 True
        logging.debug("未检测到 Cloudflare 挑战，或已自动通过。")
        return True


    except Exception as e:
        logging.error(f"解决 Cloudflare 验证码时发生错误: {e}")
        return False


def attempt_login(context: BrowserContext, email: str, password: str) -> Tuple[bool, str]:
    """
    尝试登录WebHost账户，并处理 Cloudflare 验证。 每次使用新指纹
    """
    logging.info(f"尝试登录账户: {email}")
    try:
        # 创建新页面，使用 context
        page = context.new_page()

        # 导航到登录页面，增加超时时间
        logging.debug(f"导航到登录页面: https://client.webhostmost.com/login")
        try:
            page.goto("https://client.webhostmost.com/login", timeout=20000) # 增加超时时间
        except TimeoutError as e:
            logging.error(f"导航到登录页面超时: {e}")
            return False, f"登录失败：导航超时"

        #  尝试解决 Cloudflare 验证
        solve_cloudflare_challenge(page)

        #  确保页面已经加载完毕 (在解决 Cloudflare 验证之后)
        try:
            page.wait_for_load_state("networkidle", timeout=20000) # 确保页面完全加载
        except TimeoutError as e:
            logging.error(f"页面加载超时 (解决 Cloudflare 验证后): {e}")
            return False, "登录失败: 页面加载超时 (解决 Cloudflare 验证后)"

        # 填写登录表单
        logging.debug(f"填写电子邮件地址: {email}")
        page.get_by_placeholder("Enter email").click()
        page.get_by_placeholder("Enter email").fill(email)
        logging.debug(f"填写密码: [隐藏]")
        page.get_by_placeholder("Password").click()
        page.get_by_placeholder("Password").fill(password)

        # 提交登录表单
        logging.debug("点击登录按钮")
        page.get_by_role("button", name="Login").click()

        # 改进的错误消息检测 (与之前相同)
        try:
            page.locator(".MuiAlert-message").wait_for(timeout=5000)
            error_message = page.locator(".MuiAlert-message").inner_text()
            logging.warning(f"登录失败 (错误消息): {error_message}")
            return False, f"登录失败 (错误消息): {error_message}"
        except TimeoutError:
            logging.debug("未检测到错误消息，尝试检测登录成功...")
            # 尝试检测登录成功
            try:
                page.wait_for_url("https://client.webhostmost.com/clientarea.php", timeout=5000)
                logging.info("登录成功（重定向检测）!")
                return True, "登录成功（重定向检测）!"  # 登录成功的常见情况

            except TimeoutError:
                # 检查是否登录成功，通过页面内容判断 (更健壮的检测)
                try:
                    # ** 关键:  这里需要根据实际的页面内容来判断是否登录成功。
                    #      请使用浏览器开发者工具来检查登录成功后的页面，
                    #      找到一个独特的元素或文本，用于判断。
                    # 示例：  假设登录成功后，页面上有用户名显示在某个元素中。
                    #        请根据实际情况修改这段代码
                    page.locator("text=Welcome, ").wait_for(timeout=5000) #  比如用户名或者登录后的欢迎语
                    logging.info("登录成功 (页面内容检测)!")
                    return True, "登录成功 (页面内容检测)!"
                except TimeoutError:
                    return False, "登录失败：无法重定向或检测页面内容变化"
        finally: # 确保页面关闭
            page.close()


    except TimeoutError as e:
        return False, f"登录超时：{str(e)}"
    except Exception as e:
        return False, f"登录尝试失败 (一般错误): {str(e)}"



# ... login_webhost 函数 (与之前相同，但要调整 launch_options) ...
def login_webhost(email: str, password: str, max_retries: int = 5) -> str:
    """
    尝试使用重试机制登录WebHost账户，每次使用新的指纹，模拟浏览器
    """
    logging.info(f"开始登录账户 {email}, 最大重试次数: {max_retries}")
    proxy_urls_str = os.environ.get("PROXY_URLS")

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True,
           firefox_user_prefs={  # 调整 Firefox 用户偏好设置，增强绕过验证的能力
                "network.cookie.cookieBehavior": 0,  # 接受所有 cookie
                "network.http.max-connections": 256,
                "network.http.max-persistent-connections-per-proxy": 16,
                "network.http.max-persistent-connections-per-server": 8,
            }
        )  # 启动浏览器，只启动一次

        for attempt in range(max_retries):
            try:
                # 1. 创建一个具有随机指纹的新浏览器上下文
                context = browser.new_context(
                    user_agent=generate_user_agent(navigator="firefox"),
                    user_data_dir=f"user_data_{email}_{attempt}", # 使用新的用户数据目录
                    viewport={'width': 1920, 'height': 1080},  #  设置视口大小
                    locale="en-US",  #  设置语言
                    timezone_id="America/Los_Angeles",  #  设置时区

                )

                if proxy_urls_str:
                    proxy_urls = [url.strip() for url in proxy_urls_str.split(';')]  # 分割代理URL, 去除空格
                    if proxy_urls:
                        # 随机选择一个代理
                        selected_proxy_url = random.choice(proxy_urls)
                        logging.info(f"使用随机选择的代理: {selected_proxy_url}")
                        try:
                            # 解析代理 URL
                            parsed_url = urllib.parse.urlparse(selected_proxy_url)

                            # 检查URL是否有效.
                            if parsed_url.scheme and parsed_url.netloc:
                                # 获取用户名和密码
                                if parsed_url.username is not None and parsed_url.password is not None:

                                    proxy_server = f"{parsed_url.scheme}://{parsed_url.netloc}"  # 构建server地址
                                    proxy_username = parsed_url.username
                                    proxy_password = parsed_url.password
                                    context.set_extra_http_headers({"Proxy-Authorization": f"Basic {b64encode(f'{proxy_username}:{proxy_password}'.encode()).decode()}"})
                                    context.set_default_proxy({
                                        "server": proxy_server
                                    })

                                    logging.info(f"使用代理服务器: {proxy_server}")
                                else:
                                    logging.warning(f"代理URL格式错误，缺少用户名或密码: {selected_proxy_url}")
                            else:
                                logging.warning(f"代理URL格式错误: {selected_proxy_url}")

                        except Exception as e:
                            logging.error(f"代理URL解析错误: {e}")
                else:
                    logging.info("未配置代理服务器, 将使用无代理连接")


                # 2.  尝试登录
                success, message = attempt_login(context, email, password)
                context.close() # 关闭浏览器上下文, 释放资源
                if success:
                    logging.info(f"账户 {email} 登录成功（第 {attempt + 1}/{max_retries} 次尝试）")
                    return f"账户 {email} - {message}（第 {attempt + 1}/{max_retries} 次尝试）"
                else:
                    logging.warning(f"账户 {email} 的第 {attempt + 1}/{max_retries} 次重试：{message}")
                    time.sleep(2 * (attempt + 1))  # 指数退避
            except Exception as e:
                logging.error(f"账户 {email} 在第 {attempt + 1} 次尝试时发生错误: {e}")
                if attempt == max_retries - 1:
                    logging.error(f"账户 {email} - {max_retries} 次尝试后发生致命错误：{str(e)}")
                    return f"账户 {email} - {max_retries} 次尝试后发生致命错误：{str(e)}"
            finally:
                # 在每次尝试结束时，尝试关闭浏览器和上下文，以释放资源
                try:
                    if 'browser' in locals():
                        browser.close()
                        logging.debug("浏览器已关闭")
                except Exception as e:
                    logging.error(f"关闭浏览器时发生错误: {e}")

        return f"账户 {email} - 所有 {max_retries} 次尝试均失败。"  # 所有重试都失败


def main():
    # 从环境变量获取账户信息
    accounts = os.environ.get('WEBHOST', '').split()
    login_statuses = []

    if not accounts:
        logging.warning("未配置任何账户，请设置 WEBHOST 环境变量")
        error_message = "未配置任何账户"
        send_telegram_message(error_message)
        print(error_message)
        return # 停止执行，没有账户就没必要继续

    # 处理每个账户
    for account in accounts:
        try:
            email, password = account.split(':')
        except ValueError:
            logging.error(f"账户格式错误，请使用 email:password 格式: {account}")
            login_statuses.append(f"账户 {account} 格式错误")
            continue # 跳过这个账户，处理下一个

        status = login_webhost(email, password)
        login_statuses.append(status)
        print(status)

    # 发送结果到Telegram
    if login_statuses:
        message = "WEBHOST 登录状态：\n\n" + "\n".join(login_statuses)
        result = send_telegram_message(message)
        logging.info("消息已发送到Telegram: %s", result) # 记录Telegram发送结果
        print("消息已发送到Telegram：", result)
    else:
        error_message = "没有登录状态"
        send_telegram_message(error_message)
        print(error_message)

if __name__ == "__main__":
    main()