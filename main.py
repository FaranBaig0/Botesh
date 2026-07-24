import sys
import os
import signal
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from discord_bot import bot, DISCORD_TOKEN, db
import threading
from dashboard_server import run_standalone_server

def graceful_shutdown(sig, frame):
    signal_name = "SIGINT (Ctrl+C)" if sig == signal.SIGINT else "SIGTERM (System Termination)"
    print(f"\n🛑 Received shutdown signal: {signal_name}")
    print("⏳ Closing SQLite database connection safely...")
    try:
        db.close()
    except Exception as e:
        print(f"⚠️ Database close error: {e}")
    
    print("👋 Shutting down Discord bot cleanly. Goodbye!")
    os._exit(0)


def start():
    print("==================================================")
    print("🚀 Launching Upwork Discord Job Scraper Engine...")
    print("==================================================")

    # Start the standalone Jade & Olive dashboard server in a daemon thread
    t = threading.Thread(target=run_standalone_server, kwargs={"port": 8080}, daemon=True)
    t.start()

    # Register OS signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, graceful_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, graceful_shutdown)
    
    if not DISCORD_TOKEN:
        print("❌ Error: DISCORD_TOKEN is missing in .env file.")
        sys.exit(1)

    try:
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        graceful_shutdown(signal.SIGINT, None)
    except Exception as err:
        print(f"❌ Application Error: {err}")
        sys.exit(1)

if __name__ == "__main__":
    start()
