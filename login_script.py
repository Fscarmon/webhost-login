from playwright.sync_api import sync_playwright, TimeoutError, Page
import os
import requests
import time
from typing import Tuple
import urllib.parse
import random
import logging
from dotenv import load_dotenv
from base64 import b64encode #  用于截图的base64编码
from playwright.sync_api import Browser, BrowserContext  # 导入 Browser 和 BrowserContext


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
def send_telegram_message(message: str, screenshot_path: str = None) -> dict:
    """
    使用bot API发送Telegram消息，可以选择附带截图
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
    尝试解决 Cloudflare 人机验证
    """
    try:
        #  查找 Cloudflare 挑战页面元素的示例.  **根据实际页面结构修改！**
        #  Cloudflare 挑战通常会有一个 "checking"  或者 "please wait" 的页面
        #  或者一个 “I am human”的复选框

        # 检查是否出现了 Cloudflare 挑战页面
        if page.locator("h1:has-text('Just a moment')").count() > 0:  #  **修改：根据页面实际情况修改选择器**
            logging.warning("检测到 Cloudflare 人机验证 (Just a moment)。 尝试等待自动解决...")

            #  Cloudflare 有时会自动解决，等待一段时间
            page.wait_for_load_state("networkidle", timeout=20000) # 稍微延长等待时间
            time.sleep(5) # 额外等待
            if page.url == "https://client.webhostmost.com/login":  # 如果重定向回登录页，说明解决了
                logging.info("Cloudflare 人机验证已自动解决。")
                return True # 自动解决了
            else:
                logging.warning("Cloudflare 人机验证未自动解决。")
                return False  # 没有自动解决

        # 检查是否存在 “I am human” 复选框 (示例, 请根据实际页面元素修改)
        #  Cloudflare 可能会出现 "I am human"  的复选框
        if page.locator("#challenge-form").count() > 0:  #  **修改：根据页面实际情况修改选择器**
            logging.warning("检测到 Cloudflare 人机验证 (I am human 复选框)。 尝试手动解决...")
            screenshot_path = "cloudflare_challenge.png"
            page.screenshot(path=screenshot_path)
            message = "Cloudflare 人机验证需要手动解决。 请查看截图并解决验证码，然后继续。 请手动解决后，重新运行脚本。"
            send_telegram_message(message, screenshot_path)
            #  暂停程序执行，等待用户手动解决。  请在 shell 中执行
            input("请解决验证码，然后按 Enter 继续...")
            return True #  手动解决后，认为可以继续尝试

        # 如果没有找到以上元素，也认为没有验证码，直接返回 True
        logging.debug("未检测到 Cloudflare 挑战，或已自动通过。")
        return True


    except Exception as e:
        logging.error(f"解决 Cloudflare 验证码时发生错误: {e}")
        return False

def attempt_login(page, email: str, password: str) -> Tuple[bool, str]:
    """
    尝试登录WebHost账户，并处理 Cloudflare 验证。
    """
    logging.info(f"尝试登录账户: {email}")
    try:
        # 导航到登录页面
        logging.debug(f"导航到登录页面: https://client.webhostmost.com/login")
        page.goto("https://client.webhostmost.com/login", timeout=10000)

        #  尝试解决 Cloudflare 验证
        if not solve_cloudflare_challenge(page):
            return False, "登录失败：无法解决 Cloudflare 验证"

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

    except TimeoutError as e:
        return False, f"登录超时：{str(e)}"
    except Exception as e:
        return False, f"登录尝试失败 (一般错误): {str(e)}"

# ... login_webhost 函数 (与之前相同，但要调整 launch_options) ...
def login_webhost(email: str, password: str, max_retries: int = 5) -> str:
    """
    尝试使用重试机制登录WebHost账户
    """
    logging.info(f"开始登录账户 {email}, 最大重试次数: {max_retries}")
    proxy_urls_str = os.environ.get("PROXY_URLS")

    with sync_playwright() as p:
        launch_options = {
            "headless": True,
            "firefox_user_prefs": {  # 调整 Firefox 用户偏好设置，增强绕过验证的能力
                "network.cookie.cookieBehavior": 0,  # 接受所有 cookie
                "network.http.max-connections": 256,
                "network.http.max-persistent-connections-per-proxy": 16,
                "network.http.max-persistent-connections-per-server": 8,
            }
        }

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
                            launch_options["proxy"] = {
                                "server": proxy_server,
                                "username": proxy_username,
                                "password": proxy_password,
                            }
                            logging.info(f"使用代理服务器: {proxy_server}")
                        else:
                            logging.warning(f"代理URL格式错误，缺少用户名或密码: {selected_proxy_url}")
                    else:
                        logging.warning(f"代理URL格式错误: {selected_proxy_url}")

                except Exception as e:
                    logging.error(f"代理URL解析错误: {e}")
            else:
                logging.warning("未配置任何代理服务器.") # 没有分割出代理

        else:
            logging.info("未配置代理服务器, 将使用无代理连接")

        try:
            browser = p.firefox.launch(**launch_options)  #  使用 launch_options 启动浏览器
        except Exception as e:
            logging.error(f"启动浏览器失败: {e}")
            return f"账户 {email} - 启动浏览器失败：{str(e)}"

        page = browser.new_page()

        attempt = 1
        while attempt <= max_retries:
            try:
                success, message = attempt_login(page, email, password)
                if success:
                    logging.info(f"账户 {email} 登录成功（第 {attempt}/{max_retries} 次尝试）")
                    return f"账户 {email} - {message}（第 {attempt}/{max_retries} 次尝试）"

                # 如果不成功且还有重试机会
                if attempt < max_retries:
                    logging.warning(f"账户 {email} 的第 {attempt}/{max_retries} 次重试：{message}")
                    time.sleep(2 * attempt)  # 指数退避
                else:
                    logging.error(f"账户 {email} - 所有 {max_retries} 次尝试均失败。最后错误：{message}")
                    return f"账户 {email} - 所有 {max_retries} 次尝试均失败。最后错误：{message}"

            except Exception as e:
                logging.error(f"账户 {email} 在第 {attempt} 次尝试时发生错误: {e}")
                if attempt == max_retries:
                    logging.error(f"账户 {email} - {max_retries} 次尝试后发生致命错误：{str(e)}")
                    return f"账户 {email} - {max_retries} 次尝试后发生致命错误：{str(e)}"

            finally:  # 确保浏览器关闭
                try:
                    browser.close()
                    logging.debug("浏览器已关闭")
                except Exception as e:
                    logging.error(f"关闭浏览器时发生错误: {e}")
            attempt += 1

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