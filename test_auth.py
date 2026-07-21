import os
from dotenv import load_dotenv
from auth_manager import AuthManager

load_dotenv()

def test_my_auth():
    print("🚀 --- Starting AuthManager Guest Token Test ---")
    
    # 1. Initialize AuthManager
    manager = AuthManager()
    
    # 2. Token extraction process trigger karein
    print("\n⏳ Attempting SeleniumBase guest token extraction (takes 10-15 seconds)...")
    cookies, token = manager.refresh_tokens()
    
    # 3. Results verify karein
    print("\n📊 --- TEST RESULTS ---")
    if token:
        print("✅ SUCCESS! AuthManager extracted guest token perfectly.")
        print(f"🔑 Bearer Token (First 40 chars): {token[:40]}...")
        if cookies:
            print(f"🍪 Cookies String (First 50 chars): {cookies[:50]}...")
    else:
        print("❌ FAILED! Could not extract visitor token. Check automation.log for details.")

if __name__ == "__main__":
    test_my_auth()