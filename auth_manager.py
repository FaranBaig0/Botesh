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
        """Loads active session token and cookies from session_cache.json or environment."""
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
                            self.user_cookies = data.get("user_cookies") or self.guest_cookies
                            self.is_authenticated = True
                            safe_print("💾 Loaded session token & cookies from session_cache.json! Client Analytics ENABLED!")
                            return
            except Exception as e:
                safe_print(f"⚠️ Error reading session_cache.json: {e}")

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
                # No selenium_profile needed - pure visitor session
                driver = Driver(uc=True, headless=True)

                # Step 1: Visit homepage to get base cookies
                driver.uc_open("https://www.upwork.com/")
                time.sleep(2)

                # Step 2: Visit a job details page to trigger JobDetailsNuxt_vt generation
                driver.uc_open("https://www.upwork.com/nx/search/jobs/details/~022080259272497837564")
                time.sleep(3)

                selenium_cookies = driver.get_cookies()
                cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in selenium_cookies])

                # Priority: JobDetailsNuxt_vt > UniversalSearchNuxt_vt > visitor_gql_token
                visitor_token = None
                for priority_name in ['JobDetailsNuxt_vt', 'UniversalSearchNuxt_vt', 'visitor_gql_token']:
                    for c in selenium_cookies:
                        if c.get('name') == priority_name and c.get('value'):
                            visitor_token = c['value']
                            safe_print(f"🔑 Extracted {priority_name} from job details page!")
                            break
                    if visitor_token:
                        break

                if not visitor_token:
                    # Fallback: any oauth2v2_ token
                    for c in selenium_cookies:
                        if 'oauth2v2_' in c.get('value', ''):
                            visitor_token = c['value']
                            break

                if visitor_token:
                    self.token_timestamp = datetime.now()
                    token_str = f"Bearer {visitor_token}" if not visitor_token.startswith("Bearer ") else visitor_token
                    self.guest_cookies = cookie_string
                    self.guest_token = token_str
                    self.user_token = token_str
                    self.user_cookies = cookie_string
                    self.is_authenticated = True
                    self._save_cache()
                    safe_print("🔑 Headless visitor token extracted & cached! Client details ENABLED without login!")
                    return cookie_string, token_str

                safe_print("⚠️ [AuthManager] Failed to find visitor token in headless mode.")

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
        if not self.user_token or self.should_refresh():
            self.refresh_tokens(force=False)

        headers = base_headers.copy()
        token_to_use = self.user_token or self.guest_token
        cookies_to_use = self.user_cookies or self.guest_cookies

        if token_to_use:
            headers["authorization"] = token_to_use
        if cookies_to_use:
            headers["cookie"] = cookies_to_use
        return headers