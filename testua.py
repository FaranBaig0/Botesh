import asyncio
from auth_manager import AuthManager

async def test_ua_sync():
    print("🧪 Testing Dynamic User-Agent Sync...")
    
    auth = AuthManager()
    
    # Check if loaded from cache
    if auth.last_user_agent:
        print(f"✅ UA loaded from cache: {auth.last_user_agent}")
        return

    # Force a fresh browser token extraction
    print("🔄 No cache found. Launching SeleniumBase to extract token...")
    cookies, token = await asyncio.to_thread(auth.refresh_tokens, True)
    
    print("\n─── TEST RESULTS ───")
    print(f"Token:    {'✅ Found' if token else '❌ None'}")
    print(f"Cookies:  {'✅ Found' if cookies else '❌ None'}")
    print(f"UA Synced: {'✅ ' + auth.last_user_agent if auth.last_user_agent else '❌ None'}")

asyncio.run(test_ua_sync())