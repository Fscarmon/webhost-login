import os
import re
from playwright.sync_api import Playwright, sync_playwright, expect
import requests
import time
import random
from typing import List, Tuple

class WebHostLogin:
    def __init__(self):
        self.tg_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.tg_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.max_retries = 10
        self.telegram_enabled = bool(self.tg_bot_token and self.tg_chat_id)
        
    def generate_random_fingerprint(self) -> dict:
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Edge/121.0.0.0"
        ]
        
        screen_sizes = [
            {'width': 1920, 'height': 1080},
            {'width': 1366, 'height': 768},
            {'width': 1440, 'height': 900},
            {'width': 1536, 'height': 864},
            {'width': 2560, 'height': 1440}
        ]
        
        languages = ['en-US', 'en-GB', 'zh-CN', 'zh-TW', 'ja-JP', 'ko-KR', 'fr-FR', 'de-DE']
        timezones = ['Asia/Shanghai', 'America/New_York', 'Europe/London', 'Asia/Tokyo', 'Europe/Paris']
        
        viewport = random.choice(screen_sizes)
        return {
            'viewport': viewport,
            'user_agent': random.choice(user_agents),
            'locale': random.choice(languages),
            'timezone_id': random.choice(timezones),
            'color_scheme': 'no-preference',
            'reduced_motion': 'no-preference',
            'has_touch': random.choice([True, False]),
            'is_mobile': False,
            'device_scale_factor': random.choice([1, 2])
        }

    def send_notification(self, message: str) -> None:
        print(message)
        if self.telegram_enabled:
            try:
                telegram_api_url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
                payload = {
                    "chat_id": self.tg_chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }
                requests.post(telegram_api_url, json=payload)
            except Exception as e:
                print(f"Telegram通知发送失败: {e}")

    def parse_accounts(self, accounts_str: str) -> List[Tuple[str, str]]:
        accounts = []
        for account in accounts_str.strip().split():
            try:
                username, password = account.split(':')
                accounts.append((username, password))
            except ValueError:
                print(f"无效的账号格式: {account}")
        return accounts

    def attempt_login(self, page, username: str, password: str) -> bool:
        """单次登录尝试，添加调试信息"""
        try:
            print(f"开始访问登录页面...")
            page.goto("https://client.webhostmost.com/login")
            time.sleep(10)
            print(f"当前URL: {page.url}")
            
            print(f"填写用户名: {username}")
            page.get_by_placeholder("Enter email").fill(username)
            
            print("填写密码...")
            page.get_by_placeholder("Password").fill(password)
            
            print("点击登录按钮...")
            page.get_by_role("button", name="Login").click()
            time.sleep(10)
            # 等待URL变化
            print("等待页面跳转...")
            start_time = time.time()
            while time.time() - start_time < 10:  # 10秒超时
               try:
                 page.goto("https://client.webhostmost.com/clientarea.php")
                 current_url = page.url
                 print(f"当前URL: {current_url}")
                 if "clientarea.php" in current_url:
                    print("✅ 检测到成功跳转到clientarea.php")
                    return True
                 time.sleep(5)
               except:
                  pass
               
            print("❌ 未检测到成功跳转")
            return False
            
        except Exception as e:
            print(f"登录过程出错: {str(e)}")
            return False

    def login_account(self, playwright: Playwright, username: str, password: str) -> bool:
        retry_count = 0
        
        while retry_count < self.max_retries:
            fingerprint = self.generate_random_fingerprint()
            
            try:
                browser = playwright.firefox.launch(headless=True)
                context = browser.new_context(**fingerprint)
                page = context.new_page()
                
                retry_count += 1
                current_attempt = f"(尝试 {retry_count}/{self.max_retries})"
                
                fingerprint_info = f"使用指纹:\nUA: {fingerprint['user_agent']}\n区域: {fingerprint['locale']}\n时区: {fingerprint['timezone_id']}"
                print(f"\n{current_attempt} {fingerprint_info}\n")
                
                login_result = self.attempt_login(page, username, password)
                print(f"登录结果: {'成功' if login_result else '失败'}")
                
                if login_result:
                    success_msg = f"✅ 账号登录成功 {current_attempt}: {username}\n{fingerprint_info}"
                    self.send_notification(success_msg)
                    context.close()
                    browser.close()
                    return True
                else:
                    fail_msg = f"❌ 账号登录失败 {current_attempt}: {username}\n{fingerprint_info}"
                    self.send_notification(fail_msg)
                    
                    context.close()
                    browser.close()
                    
                    if retry_count < self.max_retries:
                        print(f"🔄 准备第 {retry_count + 1} 次重试: {username}")
                        time.sleep(5)
                    
            except Exception as e:
                error_msg = f"⚠️ 登录过程出错 {current_attempt} {username}: {str(e)}\n{fingerprint_info}"
                self.send_notification(error_msg)
                
                try:
                    if 'context' in locals():
                        context.close()
                    if 'browser' in locals():
                        browser.close()
                except:
                    pass
                
                if retry_count < self.max_retries:
                    time.sleep(5)
                continue
        
        final_fail_msg = f"❌ 账号 {username} 已达到最大重试次数 ({self.max_retries}次)，放弃尝试"
        self.send_notification(final_fail_msg)
        return False

    def run_multiple_logins(self) -> None:
        accounts_str = os.getenv('WEBHOST')
        if not accounts_str:
            raise ValueError("请设置 WEBHOST 环境变量")
            
        accounts = self.parse_accounts(accounts_str)
        
        if not accounts:
            print("没有提供有效的账号")
            return
            
        with sync_playwright() as playwright:
            for username, password in accounts:
                self.login_account(playwright, username, password)
                time.sleep(2)

def main():
    try:
        login_manager = WebHostLogin()
        login_manager.run_multiple_logins()
    except Exception as e:
        print(f"程序运行出错: {e}")

if __name__ == "__main__":
    main()
