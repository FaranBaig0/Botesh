import sys
import os
import re
import sqlite3
import json
import asyncio
from datetime import datetime

class LoggerTee:
    """Redirects stdout & stderr so everything printed in terminal is also written to bot.log with timestamps."""
    def __init__(self, filename="bot.log"):
        self.terminal = sys.stdout
        self.log_file = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        if message.strip():
            timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S] ")
            if not message.startswith("["):
                self.log_file.write(timestamp + message + "\n")
            else:
                self.log_file.write(message + "\n")
        self.log_file.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

sys.stdout = LoggerTee("bot.log")
sys.stderr = LoggerTee("bot.log")

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from auth_manager import AuthManager
from database import JobDB
from scraper import (
    clean_text,
    get_current_time_24h,
    format_posted_ago,
    format_budget,
    get_experience_level,
    clean_experience_level,
    get_job_duration,
    format_proposal_count,
    fetch_target_jobs,
    fetch_job_details,
)

auth_manager = AuthManager()
load_dotenv()

def load_config():
    config_path = "config.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Error reading config.json: {e}")
    return {
        "tracked_urls": [
            {
                "label": os.getenv("UPWORK_SEARCH_TERM", "python"),
                "userQuery": os.getenv("UPWORK_SEARCH_TERM", "python"),
                "channel_id": int(os.getenv("DISCORD_CHANNEL_ID", "0"))
            }
        ],
        "fetch_interval": 30
    }

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise EnvironmentError("Missing DISCORD_TOKEN in .env")

_raw_channel_id = os.getenv("DISCORD_CHANNEL_ID")
if not _raw_channel_id:
    raise EnvironmentError("Missing DISCORD_CHANNEL_ID in .env")
CHANNEL_ID = int(_raw_channel_id)

SEARCH_TERM = os.getenv("UPWORK_SEARCH_TERM", "python")
UPWORK_BEARER_TOKEN = os.getenv("UPWORK_BEARER_TOKEN", "")

# Load token and cookies from auth_manager cache or fallback to .env
initial_auth = auth_manager.last_token or (f"Bearer {UPWORK_BEARER_TOKEN}" if UPWORK_BEARER_TOKEN and not UPWORK_BEARER_TOKEN.startswith("Bearer ") else UPWORK_BEARER_TOKEN)
initial_cookies = auth_manager.last_cookies or 'enabled_ff=!CI12577UniversalSearch,!Fluid; visitor_id=39.45.46.214.1784269223701000'

INTENTS = discord.Intents.default()
INTENTS.message_content = True
bot = commands.Bot(command_prefix="!", intents=INTENTS)

HEADERS = {
    'accept': '*/*',
    'accept-language': 'en-GB,en-US;q=0.9,en;q=0.8',
    'authorization': initial_auth if initial_auth else "",
    'cookie': initial_cookies,
    'content-type': 'application/json',
    'origin': 'https://www.upwork.com',
    'priority': 'u=1, i',
    'referer': 'https://www.upwork.com/nx/search/jobs/?q=python%20developer',
    'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    'sec-ch-ua-arch': '""',
    'sec-ch-ua-bitness': '"64"',
    'sec-ch-ua-full-version': '"150.0.7871.115"',
    'sec-ch-ua-full-version-list': '"Not;A=Brand";v="8.0.0.0", "Chromium";v="150.0.7871.115", "Google Chrome";v="150.0.7871.115"',
    'sec-ch-ua-mobile': '?1',
    'sec-ch-ua-model': '"Pixel 9"',
    'sec-ch-ua-platform': '"Android"',
    'sec-ch-ua-platform-version': '"15"',
    'sec-ch-viewport-width': '636',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36',
    'x-upwork-accept-language': 'en-US',
}

db = JobDB("jobs.db")

# Seed initial targets into SQLite DB from config.json if DB table is empty
initial_config = load_config()
db.seed_initial_targets(initial_config.get("tracked_urls", []))


@bot.event
async def on_ready():
    print(f"🤖 Bot successfully logged in as {bot.user}")
    if not job_scraper_loop.is_running():
        job_scraper_loop.start()





@bot.command(name="create")
async def create_channel_command(ctx, *, channel_name: str):
    """Command: !create <channel_name> -> Creates a Discord channel ONLY (no keyword added to DB)."""
    clean_name = channel_name.strip().lower().replace(' ', '-')
    if not clean_name:
        await ctx.send("⚠️ Usage: `!create <channel_name>` (e.g. `!create react-jobs`)")
        return

    guild = ctx.guild
    existing_channel = discord.utils.get(guild.text_channels, name=clean_name)
    if existing_channel:
        await ctx.send(f"ℹ️ Channel <#{existing_channel.id}> already exists!")
        return

    try:
        category = ctx.channel.category if hasattr(ctx.channel, 'category') else None
        new_channel = await guild.create_text_channel(name=clean_name, category=category)
        print(f"✨ [Command] Created channel #{new_channel.name} ({new_channel.id}) without keywords.")
        await ctx.send(f"✅ Created channel <#{new_channel.id}>!")
        await new_channel.send(
            f"🎉 **Channel Created!**\n"
            f"Type `!track <keyword>` inside this channel to start tracking jobs!"
        )
    except Exception as err:
        await ctx.send(f"❌ Failed to create channel: {err}\nMake sure the bot has `Manage Channels` permission.")


@bot.command(name="search")
async def search_command(ctx, *, query: str):
    """Command: !search <keyword> -> Creates a new channel AND adds keyword to SQLite DB."""
    query = query.strip().lower()
    if not query:
        await ctx.send("⚠️ Usage: `!search <keyword>` (e.g. `!search flutter`)")
        return

    clean_channel_name = f"{query.replace(' ', '-')}-jobs"
    guild = ctx.guild

    existing_channel = discord.utils.get(guild.text_channels, name=clean_channel_name)
    if existing_channel:
        label = f"{query.title()} Jobs"
        db.add_target(existing_channel.id, label, query)
        await ctx.send(f"ℹ️ Channel <#{existing_channel.id}> already exists! Registered query **`{query}`** in database.")
        return

    try:
        category = ctx.channel.category if hasattr(ctx.channel, 'category') else None
        new_channel = await guild.create_text_channel(name=clean_channel_name, category=category)
        
        label = f"{query.title()} Jobs"
        db.add_target(new_channel.id, label, query)
        
        print(f"✨ [Command] Created channel #{new_channel.name} ({new_channel.id}) for query '{query}'")
        await ctx.send(f"✅ Created channel <#{new_channel.id}> and registered query **`{query}`** in database!")
        
        await new_channel.send(
            f"🎉 **Channel Created & Tracking Active!**\n"
            f"This channel is tracking Upwork jobs for query: **`{query}`**.\n"
            f"Type `!delete` inside this channel to delete it at any time!"
        )
    except Exception as err:
        await ctx.send(f"❌ Failed to create channel: {err}\nMake sure the bot has `Manage Channels` permission.")



@bot.command(name="delete")
async def delete_channel_command(ctx, *, channel_name: str = None):
    """Command: !delete [channel_name] -> Deletes specified channel or current channel if omitted."""
    guild = ctx.guild

    if channel_name:
        clean_target = channel_name.strip().lower().replace(' ', '-')
        # Try exact match first, then with -jobs suffix
        target_channel = discord.utils.get(guild.text_channels, name=clean_target)
        if not target_channel:
            target_channel = discord.utils.get(guild.text_channels, name=f"{clean_target}-jobs")
        
        if not target_channel:
            await ctx.send(f"❌ Could not find channel `#{clean_target}` or `#{clean_target}-jobs` on this server.")
            return
    else:
        target_channel = ctx.channel

    if not isinstance(target_channel, discord.TextChannel):
        await ctx.send("⚠️ This command can only delete text channels.")
        return

    db.remove_target(target_channel.id)
    print(f"🗑️ [Command] Deleting channel #{target_channel.name} ({target_channel.id}) and removing from DB...")

    if target_channel.id == ctx.channel.id:
        await ctx.send(f"👋 Deleting channel <#{target_channel.id}> ")
        await asyncio.sleep(3)
        try:
            await target_channel.delete()
        except Exception as err:
            print(f"⚠️ Failed to delete channel: {err}")
    else:
        try:
            ch_name = target_channel.name
            await target_channel.delete()
            await ctx.send(f"✅ Successfully deleted channel **#{ch_name}**!")
        except Exception as err:
            await ctx.send(f"❌ Failed to delete channel: {err}")



@bot.command(name="track")
async def track_command(ctx, *, query: str):
    """Command: !track <keyword> -> Binds current channel to keyword in SQLite database."""
    query = query.strip()
    if not query:
        await ctx.send("⚠️ Usage: `!track <keyword>` (e.g. `!track react` or `!track machine learning`)")
        return
    label = f"{query.title()} Jobs"
    db.add_target(ctx.channel.id, label, query)
    print(f"📌 [Command] Tracked channel #{ctx.channel.name} ({ctx.channel.id}) -> Query: '{query}'")
    await ctx.send(
        f"✅ **Target Saved to Database!**\n"
        f"Channel <#{ctx.channel.id}> is now tracking Upwork jobs for query: **`{query}`**!"
    )


@bot.command(name="untrack")
async def untrack_command(ctx):
    """Command: !untrack -> Removes current channel from SQLite tracking database."""
    removed = db.remove_target(ctx.channel.id)
    if removed:
        print(f"🗑️ [Command] Untracked channel #{ctx.channel.name} ({ctx.channel.id})")
        await ctx.send(f"🗑️ **Untracked!** Removed <#{ctx.channel.id}> from active job scraping.")
    else:
        await ctx.send("ℹ️ This channel was not actively tracked in the database.")


@bot.command(name="targets", aliases=["list"])
async def list_targets_command(ctx):
    """Command: !targets -> Lists all active tracked channels and keywords from SQLite database."""
    targets = db.get_all_targets()
    if not targets:
        await ctx.send("ℹ️ No active targets currently tracked in the database.")
        return
    
    msg_lines = ["📋 **Active Tracked Search Targets (SQLite DB):**\n"]
    for t in targets:
        cid = t.get("channel_id")
        lbl = t.get("label")
        qry = t.get("userQuery")
        msg_lines.append(f"• <#{cid}> | **{lbl}** (`{qry}`)")
    
import psutil

def check_memory_usage():
    try:
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / (1024 * 1024)
        print(f"📊 Process RSS Memory Usage: {memory_mb:.2f} MB")
        if memory_mb > 500:
            print(f"⚠️ WARNING: High memory usage detected ({memory_mb:.2f} MB > 500 MB threshold)")
    except Exception as e:
        print(f"⚠️ Memory check exception: {e}")

async def post_message_safely(destination, content=None, name=None, auto_archive_duration=60, max_retries=3):
    """Safely posts messages or creates threads with automatic 429 rate limit retries."""
    for attempt in range(max_retries):
        try:
            if name is not None:
                return await destination.create_thread(name=name, auto_archive_duration=auto_archive_duration)
            else:
                return await destination.send(content)
        except discord.HTTPException as err:
            if err.status == 429:
                retry_after = getattr(err, 'retry_after', 2.0) or 2.0
                print(f"⏳ Discord 429 Rate Limit hit. Retrying in {retry_after:.1f}s (Attempt {attempt+1}/{max_retries})...")
                await asyncio.sleep(retry_after + 0.5)
            else:
                print(f"⚠️ Discord HTTP Error {err.status}: {err}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.5)
                else:
                    return None
        except Exception as exc:
            print(f"⚠️ Discord sending error: {exc}")
            return None
async def scrape_single_target(target: dict):
    global HEADERS
    label = target.get("label", target.get("userQuery", "default"))
    query = target.get("userQuery", SEARCH_TERM)
    channel_id = target.get("channel_id", CHANNEL_ID)

    channel = bot.get_channel(channel_id)
    if not channel:
        print(f"❌ Error: Channel ID {channel_id} for target '{label}' not found.")
        return

    print(f"🔍 [Concurrent] Processing Target: [{label}] (Query: '{query}') -> Channel: {channel_id}")

    # Fetch jobs via scraper engine
    jobs, HEADERS = await fetch_target_jobs(query, HEADERS, auth_manager)
    if not jobs:
        return

    print(f"✅ [{label}] Fetched {len(jobs)} jobs. Checking for new ones...")

    for item in reversed(jobs):
        job_id = item.get("id", "N/A")

        if not db.is_new(job_id, label):
            continue

        clean_title = clean_text(item.get("title", "No Title"))
        full_desc = clean_text(item.get("description", ""))
        skills_list = [skill.get('prefLabel', '').lower() for skill in item.get('ontologySkills', []) if skill.get('prefLabel')]

        # Strict keyword matching: Ensure query terms exist in Title, Description, or Skills
        query_terms = [t.strip().lower() for t in query.split() if t.strip()]
        searchable_text = f"{clean_title.lower()} {full_desc.lower()} {' '.join(skills_list)}"
        
        matches_all = all(re.search(r'\b' + re.escape(term) + r'\b', searchable_text) for term in query_terms)
        if not matches_all:
            print(f"⏭️ Skipping Job ID {job_id} [{label}]: Strict keyword terms '{query}' not matched.")
            db.mark_seen(job_id, label)
            continue

        job_inner = item.get("jobTile", {}).get("job", {})
        ciphertext = job_inner.get("ciphertext", "")
        job_url = f"https://www.upwork.com/jobs/{ciphertext}" if ciphertext else "https://www.upwork.com"

        budget_str = format_budget(job_inner)
        posted_time_ago = format_posted_ago(job_inner)
        detected_at = get_current_time_24h()
        exp_level = get_experience_level(job_inner)

        # Default fallback values for secondary details
        spent_amount = 0
        jobs_posted = "N/A"
        hire_rate_str = "N/A"
        client_location = "Not specified"
        member_since = "Not specified"
        duration_str = get_job_duration(job_inner)
        proposals = "N/A"
        payment_status = "Unverified"
        skills_str = ", ".join([s.title() for s in skills_list]) if skills_list else "Not specified"

        # Fetch secondary client info
        if ciphertext:
            print(f"🔍 Fetching deeper details for Job ID: {job_id} [{label}]...")
            details = await fetch_job_details(ciphertext, HEADERS, auth_manager)
            if details:
                opening = details.get("opening", {})
                buyer = details.get("buyer", {})
                buyer_extra = details.get("buyerExtra", {})

                # Extract applicants / proposals
                client_act = opening.get("clientActivity", {})
                total_app = client_act.get("totalApplicants")
                proposals = str(total_app) if total_app is not None else "0"

                # Extract Member Since (contractDate)
                company = buyer.get("company", {})
                contract_date = company.get("contractDate")
                if contract_date:
                    try:
                        dt = datetime.fromisoformat(contract_date.replace("Z", "+00:00"))
                        member_since = dt.strftime("%b %d, %Y")
                    except Exception:
                        member_since = contract_date.split("T")[0]

                # Extract payment verification
                if buyer_extra.get("isPaymentMethodVerified"):
                    payment_status = "Payment Verified"

                # Extract location
                loc = buyer.get("location", {})
                if loc and loc.get("country"):
                    client_location = loc.get("country")

                # Extract buyer stats
                stats = buyer.get("stats", {})
                if stats:
                    total_jobs = stats.get("totalAssignments") or 0
                    total_hires = stats.get("totalJobsWithHires") or 0
                    jobs_posted = str(total_jobs)

                    if total_jobs > 0:
                        calculated_rate = round((total_hires / total_jobs) * 100)
                        hire_rate_str = f"{calculated_rate}%"

                    total_charges = stats.get("totalCharges", {})
                    if total_charges and total_charges.get("amount") is not None:
                        spent_amount = total_charges.get("amount")

                # Extract experience level from opening if available
                raw_exp = opening.get("contractorTier")
                if raw_exp:
                    exp_level = clean_experience_level(str(raw_exp))

                # Extract engagement duration
                eng_dur = opening.get("engagementDuration", {})
                if eng_dur and eng_dur.get("label"):
                    duration_str = eng_dur.get("label")

        short_desc = clean_text(item.get("description", "No Description"))[:200] + "..."

        main_message_text = (
            f"■ **New Job Posted!** [{label}]\n"
            f"**Title:** {clean_title}\n"
            f"**Posted:** {posted_time_ago}\n"
            f"**Budget:** {budget_str}\n"
            f"**Level:** {exp_level}\n"
            f"**Time:** {detected_at}\n"
            f"**Proposals:** {proposals}\n"
            f"**Client Info:** {payment_status}, {client_location}, ${spent_amount} spent\n\n"
            f"{short_desc}\n\n"
            f"[Apply Here]({job_url})"
        )

        main_message = await post_message_safely(channel, content=main_message_text)
        if not main_message:
            print(f"❌ Failed to send main job message for Job ID {job_id}.")
            continue
            
        await asyncio.sleep(0.8)  # Delay between main message and thread creation

        try:
            thread = await post_message_safely(main_message, name=f"Job: {clean_title[:80]}", auto_archive_duration=60)
            if thread:
                await asyncio.sleep(0.8)  # Delay before sending thread content

                full_desc = clean_text(item.get('description', ''))
                if len(full_desc) > 1000:
                    truncated_desc = full_desc[:1000] + "... (truncated)"
                else:
                    truncated_desc = full_desc

                final_hire_rate = "Unknown"
                if hire_rate_str and hire_rate_str != "Unknown":
                    final_hire_rate = hire_rate_str if "%" in str(hire_rate_str) else f"{hire_rate_str}%"

                thread_details = (
                    f"**Full Job Description**:\n"
                    f"{truncated_desc}\n\n"
                    f"**Client Details**:\n"
                    f"- Total Spent: ${spent_amount}\n"
                    f"- Jobs Posted: {jobs_posted}\n"
                    f"- Hire Rate: {final_hire_rate}\n"
                    f"- Location: {client_location}\n"
                    f"- Member Since: {member_since}\n\n"
                    f"**Job Details**:\n"
                    f"- Duration: {duration_str}\n"
                    f"- Experience Level: {exp_level}\n"
                    f"- Job Type: {job_inner.get('jobType', 'Unknown').title()}\n\n"
                    f"**Required Skills:** {skills_str}\n\n"
                    f"[Apply on Upwork]({job_url})"
                )

                if len(thread_details) > 1995:
                    thread_details = thread_details[:1980] + "\n... [truncated]"

                await post_message_safely(thread, content=thread_details)
            
        except Exception as thread_err:
            print(f"⚠️ Thread content generation/sending failed: {thread_err}")
            
        db.mark_seen(job_id, label)
        await asyncio.sleep(1.2)  # Delay before processing next job in channel


@tasks.loop(seconds=30)
async def job_scraper_loop():
    print("\n📡 Loop Triggered: checking Upwork for tracked search targets (Concurrent)...")
    check_memory_usage()
    db.cleanup_old_jobs(days=30)
    
    if auth_manager.should_refresh():
        print("⏰ Proactive timer condition met. Executing background refresh...")
        new_cookies, new_auth = await asyncio.to_thread(auth_manager.refresh_tokens)
        if new_cookies and new_auth:
            HEADERS["cookie"] = new_cookies
            HEADERS["authorization"] = new_auth

    # Fetch tracked targets dynamically from SQLite Database
    tracked_targets = db.get_all_targets()

    if tracked_targets:
        tasks_list = [scrape_single_target(target) for target in tracked_targets]
        await asyncio.gather(*tasks_list)
    else:
        print("ℹ️ No tracked targets found in SQLite database.")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)

