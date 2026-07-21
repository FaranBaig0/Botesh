import os
import time
import json
import threading
from datetime import datetime, timedelta
from seleniumbase import Driver

CACHE_FILE = "session_cache.json"

class AuthManager:
    def __init__(self):
        self.token_timestamp = None
        self.token_lifetime = timedelta(hours=11)
        self.last_cookies = None
        self.last_token = None
        self.lock = threading.Lock()
        self._load_cache()

    def _load_cache(self):
        """Loads cached token and cookies from disk on startup if still valid."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    ts_str = data.get("timestamp")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if datetime.now() - ts < self.token_lifetime:
                            self.token_timestamp = ts
                            self.last_cookies = data.get("cookies")
                            self.last_token = data.get("token")
                            print("💾 Loaded valid session token & cookies from session_cache.json!")
                        else:
                            print("⌛ Cached session in session_cache.json has expired.")
            except Exception as e:
                print(f"⚠️ Error reading session_cache.json: {e}")

    def _save_cache(self):
        """Saves active token and cookies to disk."""
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": self.token_timestamp.isoformat() if self.token_timestamp else None,
                    "cookies": self.last_cookies,
                    "token": self.last_token
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving session_cache.json: {e}")

    def should_refresh(self) -> bool:
        if not self.token_timestamp:
            return True
        elapsed = datetime.now() - self.token_timestamp
        return elapsed >= self.token_lifetime

    def refresh_tokens(self, force: bool = False) -> tuple[str, str] | tuple[None, None]:
        with self.lock:
            # If token was refreshed in the last 15 seconds by a concurrent target, ALWAYS reuse it!
            if self.token_timestamp and (datetime.now() - self.token_timestamp).total_seconds() < 15:
                if self.last_cookies and self.last_token:
                    print("ℹ️ Token was recently refreshed by concurrent target. Reusing fresh token.")
                    return self.last_cookies, self.last_token

            # If not forced and token was refreshed in the last 60 seconds, reuse it!
            if not force and self.token_timestamp and (datetime.now() - self.token_timestamp).total_seconds() < 60:
                if self.last_cookies and self.last_token:
                    print("ℹ️ Token was recently refreshed. Reusing cached token.")
                    return self.last_cookies, self.last_token

            print("🔄 [AuthManager] Launching Headless SeleniumBase session for guest token...")

            # Clean up lingering driver processes to prevent profile locks
            if os.name == "nt":
                try:
                    os.system("taskkill /f /im chromedriver.exe >nul 2>&1")
                except Exception:
                    pass
            
            profile_dir = os.path.abspath("selenium_profile")
            for lock_item in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
                lf = os.path.join(profile_dir, lock_item)
                if os.path.exists(lf):
                    try:
                        os.remove(lf)
                    except Exception:
                        pass

            driver = None
            try:
                driver = Driver(uc=True, headless=True, user_data_dir=profile_dir)
                driver.uc_open_with_reconnect("https://www.upwork.com/nx/search/jobs/?q=python", reconnect_time=3)

                cookie_string = ""
                visitor_token = None

                # Fast polling loop: check cookies every 0.4s up to 12 times (max ~4.8s total)
                for _ in range(12):
                    selenium_cookies = driver.get_cookies()
                    cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in selenium_cookies])

                    # 1. Pehle specific UniversalSearchNuxt_vt token dhoondo (Job Search Token)
                    for c in selenium_cookies:
                        if c.get('name') == 'UniversalSearchNuxt_vt' and c.get('value'):
                            visitor_token = c.get('value')
                            break

                    # 2. Fallback (Agar UniversalSearchNuxt_vt na mile to visitor_topnav_gql_token ko ignore kar ke baaqi check karein)
                    if not visitor_token:
                        for c in selenium_cookies:
                            name = c.get('name', '')
                            val = c.get('value', '')
                            if name != 'visitor_topnav_gql_token' and ('_vt' in name or 'token' in name or 'Nuxt' in name) and val:
                                if 'oauth2' in val or val.startswith('oauth2v2_'):
                                    visitor_token = val
                                    break

                    if visitor_token:
                        time.sleep(2.0)  # Brief pause to ensure token activation on Upwork backend
                        break
                    time.sleep(0.4)

                if not visitor_token:
                    try:
                        visitor_token = driver.execute_script("return localStorage.getItem('visitor_gql_token');")
                        if not visitor_token:
                            visitor_token = driver.execute_script("return localStorage.getItem('oauth2_access_token');")
                    except Exception:
                        pass

                if visitor_token:
                    self.token_timestamp = datetime.now()
                    token_str = f"Bearer {visitor_token}" if not visitor_token.startswith("Bearer ") else visitor_token
                    self.last_cookies = cookie_string
                    self.last_token = token_str
                    self._save_cache()  # Save to disk for instant bot restarts
                    print("🔑 Headless guest token extracted successfully!")
                    print(f"Cookies ye hein: {cookie_string} || token ye hein: {token_str}")
                    return cookie_string, token_str
                
                print("⚠️ [AuthManager] Failed to find visitor token in headless mode.")
                    
            except Exception as err:
                print(f"❌ [AuthManager] Error details: {err}")
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    time.sleep(1.5)  # Allow process and port to release cleanly
            return None, None