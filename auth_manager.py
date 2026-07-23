import os
import time
import json
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

CACHE_FILE = "session_cache.json"
load_dotenv()

def safe_print(msg: str):
    """Safely print messages handling Windows CP1252 character encoding gracefully."""
    try:
        print(msg)
    except UnicodeEncodeError:
        safe_msg = msg.encode("ascii", "ignore").decode("ascii")
        print(safe_msg)

class AuthManager:
    def __init__(self):
        self.token_timestamp = None
        self.token_lifetime = timedelta(hours=11)
        self.guest_cookies = None
        self.guest_token = None
        self.user_token = None
        self.user_cookies = None
        self.is_authenticated = False
        self.lock = threading.Lock()
        self._load_env_or_cache()

    def _load_env_or_cache(self):
        """Loads user bearer token from environment and cached guest tokens from disk."""
        env_token = os.getenv("UPWORK_BEARER_TOKEN")
        env_cookies = os.getenv("UPWORK_COOKIES")

        if env_token and env_token.strip():
            token_str = env_token.strip()
            if not token_str.startswith("Bearer "):
                token_str = f"Bearer {token_str}"
            self.user_token = token_str
            self.user_cookies = env_cookies or ""
            self.is_authenticated = True
            safe_print("🔑 [AuthManager] Loaded user UPWORK_BEARER_TOKEN from environment. Authenticated client analytics ENABLED!")
            return

        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    ts_str = data.get("timestamp")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if datetime.now() - ts < self.token_lifetime:
                            self.token_timestamp = ts
                            self.guest_cookies = data.get("guest_cookies") or data.get("cookies")
                            self.guest_token = data.get("guest_token") or data.get("token")
                            self.user_token = data.get("user_token") or self.guest_token
                            self.is_authenticated = True
                            safe_print("💾 Loaded session token & cookies from session_cache.json with Client Analytics ENABLED!")
            except Exception as e:
                safe_print(f"⚠️ Error reading session_cache.json: {e}")

    def _save_cache(self):
        """Saves active session tokens and cookies to disk."""
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": self.token_timestamp.isoformat() if self.token_timestamp else None,
                    "guest_cookies": self.guest_cookies,
                    "guest_token": self.guest_token,
                    "user_token": self.user_token,
                    "is_authenticated": True
                }, f, indent=2)
        except Exception as e:
            safe_print(f"⚠️ Error saving session_cache.json: {e}")

    def should_refresh(self) -> bool:
        if not self.token_timestamp or not self.guest_token:
            return True
        elapsed = datetime.now() - self.token_timestamp
        return elapsed >= self.token_lifetime

    def refresh_tokens(self, force: bool = False) -> tuple[str, str] | tuple[None, None]:
        with self.lock:
            # If token was refreshed in the last 15 seconds by a concurrent target, ALWAYS reuse it!
            if self.token_timestamp and (datetime.now() - self.token_timestamp).total_seconds() < 15:
                if self.guest_cookies and self.guest_token:
                    return self.guest_cookies, self.guest_token

            # If not forced and token was refreshed in the last 60 seconds, reuse it!
            if not force and self.token_timestamp and (datetime.now() - self.token_timestamp).total_seconds() < 60:
                if self.guest_cookies and self.guest_token:
                    return self.guest_cookies, self.guest_token

            safe_print("🔄 [AuthManager] Launching Headless SeleniumBase session for guest token...")

            # Clean up lingering driver processes to prevent profile locks
            if os.name == "nt":
                try:
                    os.system("taskkill /f /im chromedriver.exe >nul 2>&1")
                    os.system("taskkill /f /im chrome.exe >nul 2>&1")
                except Exception:
                    pass

            driver = None
            try:
                from seleniumbase import Driver
                profile_dir = os.path.abspath("selenium_profile")
                driver = Driver(uc=True, user_data_dir=profile_dir, headless=True)
                driver.uc_open("https://www.upwork.com/")

                cookie_string = ""
                visitor_token = None

                # Fast polling loop: check cookies every 0.4s up to 15 times
                for _ in range(15):
                    selenium_cookies = driver.get_cookies()
                    cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in selenium_cookies])

                    for c in selenium_cookies:
                        name = c.get('name', '')
                        val = c.get('value', '')
                        if (name == 'visitor_gql_token' or name == 'UniversalSearchNuxt_vt') and val:
                            visitor_token = val
                            break
                        if 'oauth2v2_' in val and not visitor_token:
                            visitor_token = val
                            break

                    if visitor_token:
                        time.sleep(1.5)  # Brief pause to ensure token activation on Upwork backend
                        break
                    time.sleep(0.4)

                if not visitor_token:
                    try:
                        visitor_token = driver.execute_script("return localStorage.getItem('visitor_gql_token') || localStorage.getItem('oauth2_access_token');")
                    except Exception:
                        pass

                if visitor_token:
                    self.token_timestamp = datetime.now()
                    token_str = f"Bearer {visitor_token}" if not visitor_token.startswith("Bearer ") else visitor_token
                    self.guest_cookies = cookie_string
                    self.guest_token = token_str
                    if not self.user_token:
                        self.user_token = token_str
                    self.is_authenticated = True
                    self._save_cache()
                    safe_print("🔑 Headless session token extracted & cached with Client Analytics ENABLED!")
                    return cookie_string, token_str
                
                safe_print("⚠️ [AuthManager] Failed to find session token in headless mode.")
                    
            except Exception as err:
                safe_print(f"❌ [AuthManager] Error details: {err}")
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    time.sleep(1.5)
            return None, None

    def get_search_headers(self, base_headers: dict) -> dict:
        """Returns headers specifically configured for visitorJobSearchV1 API."""
        if not self.guest_token or self.should_refresh():
            self.refresh_tokens(force=False)
        
        headers = base_headers.copy()
        
        # Extract visitor_gql_token from guest_cookies if available for search authorization
        visitor_token = None
        if self.guest_cookies:
            for part in self.guest_cookies.split(";"):
                if "visitor_gql_token=" in part or "UniversalSearchNuxt_vt=" in part:
                    visitor_token = part.split("=")[1].strip()
                    break

        search_auth = f"Bearer {visitor_token}" if visitor_token else (self.guest_token or "")
        if search_auth:
            headers["authorization"] = search_auth
        if self.guest_cookies:
            headers["cookie"] = self.guest_cookies
        return headers

    def get_details_headers(self, base_headers: dict) -> dict:
        """Returns headers configured for JobPubDetails API using cached session token."""
        headers = base_headers.copy()
        token_to_use = self.user_token or self.guest_token
        cookies_to_use = self.user_cookies or self.guest_cookies

        if not token_to_use:
            self.refresh_tokens(force=False)
            token_to_use = self.user_token or self.guest_token
            cookies_to_use = self.user_cookies or self.guest_cookies

        if token_to_use:
            headers["authorization"] = token_to_use
        if cookies_to_use:
            headers["cookie"] = cookies_to_use
        return headers