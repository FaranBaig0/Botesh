import re
import json
import asyncio
from datetime import datetime
from curl_cffi import requests

UPWORK_URL = "https://www.upwork.com/api/graphql/v1?alias=visitorJobSearch"
UPWORK_DETAILS_URL = "https://www.upwork.com/api/graphql/v1?alias=gql-query-get-visitor-job-details"

GRAPHQL_PAYLOAD = {
    "query": """
    query VisitorJobSearch($requestVariables: VisitorJobSearchV1Request!) {
      search {
        universalSearchNuxt {
          visitorJobSearchV1(request: $requestVariables) {
            paging { total offset count }
            results {
              id
              title
              description
              relevanceEncoded
              ontologySkills {
                uid parentSkillUid prefLabel prettyName: prefLabel freeText highlighted
              }
              jobTile {
                job {
                  id
                  ciphertext: cipherText
                  jobType
                  weeklyRetainerBudget
                  hourlyBudgetMax
                  hourlyBudgetMin
                  hourlyEngagementType
                  contractorTier
                  sourcingTimestamp
                  createTime
                  publishTime
                  hourlyEngagementDuration { rid label weeks mtime ctime }
                  fixedPriceAmount { isoCurrencyCode amount }
                  fixedPriceEngagementDuration { id rid label weeks ctime mtime }
                }
              }
            }
          }
        }
      }
    }
    """,
    "variables": {
        "requestVariables": {
            "userQuery": "python",
            "sort": "recency+desc",
            "highlight": True,
            "paging": {"offset": 0, "count": 10},
        }
    },
}

JOB_DETAILS_QUERY = """
query JobPubDetailsQuery($id: ID!) {
  jobPubDetails(id: $id) {
    opening {
      description
      contractorTier
      workload
      clientActivity {
        totalApplicants
      }
      engagementDuration {
        label
      }
      annotations {
        customFields
      }
    }
    buyer {
      company {
        contractDate
      }
      location {
        country
      }
      stats {
        totalAssignments
        totalJobsWithHires
        totalCharges {
          amount
        }
      }
    }
    buyerExtra {
      isPaymentMethodVerified
    }
  }
}
"""

def clean_text(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"[a-zA-Z]?\^[a-zA-Z0-9\s+-]+\^[a-zA-Z]?", "", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

def get_current_time_24h() -> str:
    """Time the bot detected the job."""
    return datetime.now().strftime("%H:%M")

def parse_to_unix_seconds(raw_ts) -> int | None:
    if not raw_ts:
        return None
    if isinstance(raw_ts, (int, float)):
        val = int(raw_ts)
        return int(val / 1000) if val > 10000000000 else val
    if isinstance(raw_ts, str):
        if raw_ts.isdigit():
            val = int(raw_ts)
            return int(val / 1000) if val > 10000000000 else val
        try:
            clean_str = raw_ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            return int(dt.timestamp())
        except Exception:
            pass
    return None

def format_posted_ago(job_inner: dict) -> str:
    """Returns dynamic real-time relative counter (<t:UNIX:R>)."""
    raw_ts = job_inner.get("publishTime") or job_inner.get("sourcingTimestamp") or job_inner.get("createTime")
    unix_seconds = parse_to_unix_seconds(raw_ts)
    if not unix_seconds:
        unix_seconds = int(datetime.now().timestamp())
    return f"(<t:{unix_seconds}:R>)"

def format_budget(job_inner: dict) -> str:
    job_type = job_inner.get("jobType", "Unknown")
    if job_type == "FIXED":
        fixed_amount = job_inner.get("fixedPriceAmount")
        if fixed_amount:
            return f"${fixed_amount.get('amount')}"
        return "N/A"
    elif job_type == "HOURLY":
        min_rate = job_inner.get("hourlyBudgetMin", 0)
        max_rate = job_inner.get("hourlyBudgetMax", 0)
        return f"${min_rate} - ${max_rate}/hr"
    return "N/A"

def get_experience_level(job_inner: dict) -> str:
    tier = job_inner.get("contractorTier")
    if tier == 1:
        return "Entry"
    elif tier == 2:
        return "Intermediate"
    elif tier == 3:
        return "Expert"
    return "Not specified"

def clean_experience_level(raw_level: str) -> str:
    if not raw_level:
        return "Not specified"
    return raw_level.replace("Level", "").strip()

def get_job_duration(job_inner: dict) -> str:
    hourly_dur = job_inner.get("hourlyEngagementDuration")
    if hourly_dur and isinstance(hourly_dur, dict):
        return hourly_dur.get("label", "Not specified")
    fixed_dur = job_inner.get("fixedPriceEngagementDuration")
    if fixed_dur and isinstance(fixed_dur, dict):
        return fixed_dur.get("label", "Not specified")
    return "Not specified"

def format_proposal_count(proposals_tier: str) -> str:
    if not proposals_tier:
        return "No Proposals yet"
    tier = proposals_tier.upper().strip()
    if "LESS_THAN_FIVE" in tier:
        return "Less than 5"
    elif "FIVE_TO_TEN" in tier:
        return "5 to 10"
    elif "TEN_TO_FIFTEEN" in tier:
        return "10 to 15"
    elif "FIFTEEN_TO_TWENTY" in tier:
        return "15 to 20"
    elif "TWENTY_TO_FIFTY" in tier:
        return "20 to 50"
    elif "FIFTY_OR_MORE" in tier or "FIFTY_PLUS" in tier:
        return "50+"
    return proposals_tier.replace("_", " ").title()

async def post_with_exponential_backoff(url: str, headers: dict, payload: dict, max_retries: int = 3):
    """Executes requests.post with exponential backoff on network exceptions (2s, 4s, 8s)."""
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                requests.post, url, headers=headers, json=payload, impersonate="chrome120", timeout=15
            )
            return response
        except Exception as err:
            print(f"⚠️ Network request attempt {attempt + 1}/{max_retries} failed: {err}")
            if attempt < max_retries - 1:
                sleep_sec = 2 ** attempt
                print(f"⏳ Retrying network request in {sleep_sec}s...")
                await asyncio.sleep(sleep_sec)
            else:
                print("❌ All network retries exhausted for this cycle.")
                return None

async def fetch_target_jobs(query: str, headers: dict, auth_manager) -> tuple[list, dict]:
    """
    Fetches Upwork job search results for a query string.
    Handles 401 and empty data block token refreshes using auth_manager.
    Returns (jobs_list, updated_headers).
    """
    payload = json.loads(json.dumps(GRAPHQL_PAYLOAD))
    payload["variables"]["requestVariables"]["userQuery"] = query

    target_headers = headers.copy()
    target_headers["referer"] = f"https://www.upwork.com/nx/search/jobs/?q={requests.utils.quote(query)}"

    response = await post_with_exponential_backoff(UPWORK_URL, target_headers, payload)
    if not response:
        return [], headers

    if response.status_code == 401:
        print("❌ 401 Unauthorized hit. Refreshing session token...")
        new_cookies, new_auth = await asyncio.to_thread(auth_manager.refresh_tokens, force=True)
        if new_cookies and new_auth:
            headers["cookie"] = new_cookies
            headers["authorization"] = new_auth
            target_headers["cookie"] = new_cookies
            target_headers["authorization"] = new_auth
            response = await post_with_exponential_backoff(UPWORK_URL, target_headers, payload)
            if not response:
                return [], headers
        else:
            return [], headers

    if response.status_code != 200:
        print(f"❌ Upwork request failed for '{query}' with status: {response.status_code}")
        print(f"🔍 [DEBUG RAW TEXT]: {response.text[:500]}")
        return [], headers

    data = response.json()

    # Reactive refresh if data block is empty or contains errors
    if "data" not in data or data["data"] is None or "errors" in data:
        print(f"⚠️ Upwork returned empty data/error for '{query}'. Refreshing token...")
        new_cookies, new_auth = await asyncio.to_thread(auth_manager.refresh_tokens, force=True)
        if new_cookies and new_auth:
            headers["cookie"] = new_cookies
            headers["authorization"] = new_auth
            target_headers["cookie"] = new_cookies
            target_headers["authorization"] = new_auth
            response = await post_with_exponential_backoff(UPWORK_URL, target_headers, payload)
            if response:
                data = response.json()

    if "data" not in data or data["data"] is None:
        print(f"❌ Upwork returned empty data block for '{query}'. Skipping cycle.")
        print(f"🔍 [DEBUG RAW RESPONSE]: {data}") 
        return [], headers

    try:
        jobs = data["data"]["search"]["universalSearchNuxt"]["visitorJobSearchV1"]["results"]
        return jobs, headers
    except (KeyError, TypeError):
        return [], headers

async def fetch_job_details(ciphertext: str, headers: dict, auth_manager) -> dict | None:
    """Fetches secondary client info (total spent, hire rate, member since, location)."""
    if not ciphertext:
        return None
    payload = {
        "query": JOB_DETAILS_QUERY,
        "variables": {"id": ciphertext, "isLoggedIn": False}
    }
    try:
        response = await post_with_exponential_backoff(UPWORK_DETAILS_URL, headers, payload)
        if not response:
            return None
        
        if response.status_code == 401:
            print("⚠️ 401 Unauthorized inside job details module. Retrying refresh...")
            new_cookies, new_auth = await asyncio.to_thread(auth_manager.refresh_tokens, force=True)
            if new_cookies and new_auth:
                headers["cookie"] = new_cookies
                headers["authorization"] = new_auth
                response = await post_with_exponential_backoff(UPWORK_DETAILS_URL, headers, payload)
                if not response:
                    return None
            else:
                return None

        if response.status_code == 200:
            return response.json().get("data", {}).get("jobPubDetails", {})
    except Exception as e:
        print(f"⚠️ Secondary API Details Request Failed: {e}")
    return None

