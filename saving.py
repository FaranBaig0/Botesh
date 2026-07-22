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
                    os.system("taskkill /f /im chrome.exe >nul 2>&1")
                except Exception:
                    pass

            driver = None
            try:
                driver = Driver(uc=True, headless=True)
                driver.uc_open("https://www.upwork.com/")

                cookie_string = ""
                visitor_token = None

                # Fast polling loop: check cookies every 0.4s up to 15 times
                for _ in range(15):
                    selenium_cookies = driver.get_cookies()
                    cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in selenium_cookies])

                    # 1. Look for visitor_gql_token, UniversalSearchNuxt_vt or oauth2v2 token
                    for c in selenium_cookies:
                        name = c.get('name', '')
                        val = c.get('value', '')
                        if (name == 'visitor_gql_token' or name == 'UniversalSearchNuxt_vt') and val:
                            visitor_token = val
                            break
                        if 'oauth2v2_' in val:
                            visitor_token = val
                            break

                    if visitor_token:
                        time.sleep(2.0)  # Brief pause to ensure token activation on Upwork backend
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
                    self.last_cookies = cookie_string
                    self.last_token = token_str
                    self._save_cache()  # Save to disk for instant bot restarts
                    print("🔑 Headless guest token extracted successfully!")
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
        
        {
  "timestamp": "2026-07-22T13:29:26.844899",
  "cookies": "forterToken=20c72a2d72a64c25b9de9ad22e78ec10_1784708958483__UDF43-m4_23ck_JMaEhYsSIt0%3D-6705-v2; visitor_gql_token=oauth2v2_int_4256f7c3feab4af85fd1b86f4efd693e; _cq_session=1.1784708960512.txPcyco40KgyP9U1.1784708960512; country_code=PK; XSRF-TOKEN=Og67gxz0sTe24BNNjHyJURuIQTiZYhgT; _cq_s=gyEcI4pebFYgZLiE:ihQceGu5p54+Yn3bUH8tQzsk/C5VMx/c9yQW1Vers7muJQz5tQavY/48YVLNiXnt6Rq6nR1K8/RxYqwyJyarWotUwSL6jUWxBH6D1ReCl5KPFsRx7tzlTr5GTTeA9deytGc3kEznui70GRpsyCHNaX5Pcc/58cgpLJBAMStoX+KLn5/07KdE4n8MDJ4CfEUZyWl5KQWB7BaZxhqW45rAmanuNxGjnHxJmd58SPfkN3baKBg8DYb8poLcloSouwfG3awdLyHbm0VjRC+vQ2CJyl2ytGgE/AUqbdcMyOQweWL11Z79c5YK/888Xa5xNdbmYPZnKb6YpMpN/sQk0ds4lMVMVOjS92rJs3wZUUck3xda/EYyMOWIrkIeULDWm4g904HR/Asn8LcpewloMRZSal0+4aGoUeyxmcQQKV0D5QAsjk99:/JXT0b7hJPXtNvaiFkHBjQ==; _upw_ses.5831=*; g_state={\"i_l\":0,\"i_ll\":1784708959842,\"i_b\":\"LEzzl77l3rUALVr8CHDW1TioCImXNDt8U6VABmhyRzc\",\"i_e\":{\"enable_itp_optimization\":24},\"i_et\":1784708959842}; forterToken=20c72a2d72a64c25b9de9ad22e78ec10_1784708958483__UDF43-m4_23ck_JMaEhYsSIt0%3D-6705-v2; _gcl_au=1.1.1837093318.1784708960; _vwo_sn=0%3A1; _cq_suid=1.1784708960.EkYjS9ojZZQCzEBS; _vwo_uuid=D12A163615432ECF6A3DF964EDE4874F8; _vwo_uuid_v2=D12A163615432ECF6A3DF964EDE4874F8|7cd79e4d793affd02ae9189ff5b19039; cookie_prefix=; AWSALBTGCORS=98X977+IWAay63qSYumdNYWiufyWOAmoPsxaUoymc50z03f7CtSMwVEqBlKp0tKDooMN9UbssJpnhCdnhzVGE4Nq/aSB8IMzOS+jcj5wrZ0MFPpi5xcI2GmagdoU9gKPJKUkSgQ5EB8EuiGn2oJVkb9T4SOQ05rG5PZOYacVWsIe; enabled_ff=!CI12577UniversalSearch,!Fluid,!MP16400Air3Migration,!SSINavUser,!TranscendUIOn,!i18nGA,CI17409DarkModeUI,CmpLibOn,JPAir3,OTBnrOn,SSINavUserBpa,TONB2256Air3Migration,WP658TranscendOn,i18nOn; _vis_opt_test_cookie=1; __cflb=02DiuEXPXZVk436fJfSVuuwDqLqkhavJbgFWLRQiMqjhD; AWSALB=OWrp0PdihKc0HyOTRQNZo+Dtq24T3bAlJQM42jgSXQCrdRQmSDrHjvIIuNXMtLGyzo3FrmLHaw++O/g/DWHfgSv3ercqcA0h8yJw/uCJZEUPfb8qQHcXsDj7OZc1; spt=c3e5e7dd-b33c-4406-84d0-82192206ae38; tatari-session-cookie=58a40011-9bba-9b49-dfa2-7b5e9f94fde5; _vis_opt_s=1%7C; umq=1424; cf_clearance=YVsEoeA5IZWz1lG1YBn7n9OhUta1.GkMfW8HfhsonMQ-1784708959-1.2.1.1-76HtiTvA07Gwx7.sSTUZroT0V4ZEWLoyAChsv7LPx0.d006kMRESQ1LyBAv.hdhsTFEGu2yVbk3BLAxl8u.e19FAZsgM9kqYQB7T6H9vrE5vVdTed2w2zMPyFmtLKsX3yngZpaeWsF6JnjPlr7A3TDAMqKMgOnyYvlY1SlFKRxK74mnqWNdWGig91VdTUB1JdztEdeGnDhezxgSeDtOwef..BG9aEStb1WSGdDoBL25KRER2ddJ7Tef6fg0z88opsbE1HRlTjd22H96uhXHbB2U38.1a5FiZXz6aCGRV67hENZsWrNZg4CbupNi6_1xj3EcngJPgpWRKm4mmM4aAsA; AWSALBTG=98X977+IWAay63qSYumdNYWiufyWOAmoPsxaUoymc50z03f7CtSMwVEqBlKp0tKDooMN9UbssJpnhCdnhzVGE4Nq/aSB8IMzOS+jcj5wrZ0MFPpi5xcI2GmagdoU9gKPJKUkSgQ5EB8EuiGn2oJVkb9T4SOQ05rG5PZOYacVWsIe; _upw_id.5831=f221b179-ba52-46dd-90ba-e8688faed854.1784708960.1.1784708961..26c11e2b-3a23-4392-b60d-9237ef7c5f1d..d811873e-fa87-4d84-981a-e20f691d2844.1784708959807.10; visitor_id=39.45.46.214.1784708956178000; cookie_domain=.upwork.com; _cq_duid=1.1784708960.ssXHQ9d8xRxnImke; AWSALBCORS=OWrp0PdihKc0HyOTRQNZo+Dtq24T3bAlJQM42jgSXQCrdRQmSDrHjvIIuNXMtLGyzo3FrmLHaw++O/g/DWHfgSv3ercqcA0h8yJw/uCJZEUPfb8qQHcXsDj7OZc1; _vwo_ds=3%241784708957%3A12.4952962%3A%3A%3A%3A%3A1784708957%3A1784708957%3A1; OptanonConsent=consentId=6dc4a579-ee91-4768-aa4a-da6e1f9388f0&datestamp=Wed+Jul+22+2026+13%3A29%3A21+GMT%2B0500+(Pakistan+Standard+Time)&version=202512.1.0&isAnonUser=1&isGpcEnabled=0&browserGpcFlag=0&isIABGlobal=false&identifierType=Cookie+Unique+Id&hosts=&interactionCount=0&landingPath=https%3A%2F%2Fwww.upwork.com%2F&iType=undefined&groups=C0001%3A1%2CC0002%3A1%2CC0003%3A1%2CC0004%3A1&crTime=1784708961113; __cf_bm=pS1Bli5Ik8vsQYSk1K7elHVaoZHOL34HKCyUuMUatiI-1784708959.4041538-1.0.1.1-L590gW8vP27yEoucCdWNHRGNnIMeGz0_TRTaR5HVAcTM9iTYO2ssdA.9hb1ufdjA0RZ1wNE6FrAJcmkPRmsoqm6CXyTt_usr4SkfxklTeyTouKWCUgeI9O29Xw9cPlNB; tatari-cookie-test=78328088",
  "token": "Bearer oauth2v2_int_4256f7c3feab4af85fd1b86f4efd693e"
}