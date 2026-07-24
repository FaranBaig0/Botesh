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
fragment JobPubOpeningInfoFragment on Job {
  ciphertext
  id
  type
  access
  title
  hideBudget
  createdOn
  notSureProjectDuration
  notSureFreelancersToHire
  notSureExperienceLevel
  notSureLocationPreference
  premium
}
fragment JobPubOpeningSegmentationDataFragment on JobSegmentation {
  customValue
  label
  name
  sortOrder
  type
  value
  skill {
    description
    externalLink
    prettyName
    skill
    id
  }
}
fragment JobPubOpeningSandDataFragment on SandsData {
  occupation {
    freeText
    ontologyId
    prefLabel
    id
    uid: id
  }
  ontologySkills {
    groupId
    id
    freeText
    prefLabel
    groupPrefLabel
    relevance
  }
  additionalSkills {
    groupId
    id
    freeText
    prefLabel
    relevance
  }
}
fragment JobPubOpeningFragment on JobPubOpeningInfo {
  status
  postedOn
  publishTime
  sourcingTime
  startDate
  deliveryDate
  workload
  contractorTier
  description
  info {
    ...JobPubOpeningInfoFragment
  }
  segmentationData {
    ...JobPubOpeningSegmentationDataFragment
  }
  sandsData {
    ...JobPubOpeningSandDataFragment
  }
  category {
    name
    urlSlug
  }
  categoryGroup {
    name
    urlSlug
  }
  budget {
    amount
    currencyCode
  }
  annotations {
    customFields
    tags
  }
  engagementDuration {
    label
    weeks
  }
  extendedBudgetInfo {
    hourlyBudgetMin
    hourlyBudgetMax
    hourlyBudgetType
  }
  attachments @include(if: $isLoggedIn) {
    fileName
    length
    uri
  }
  clientActivity @include(if: $isLoggedIn) {
    lastBuyerActivity
    totalApplicants
    totalHired
    totalInvitedToInterview
    unansweredInvites
    invitationsSent
    numberOfPositionsToHire
  }
  deliverables
  deadline
  tools {
    name
  }
}
fragment JobPubBuyerInfoFragment on JobPubBuyerInfo {
  location {
    offsetFromUtcMillis
    countryTimezone
    city
    country
  }
  stats {
    totalAssignments
    activeAssignmentsCount
    hoursCount
    feedbackCount
    score
    totalJobsWithHires
    totalCharges {
      amount
    }
  }
  company {
    name @include(if: $isLoggedIn)
    companyId @include(if: $isLoggedIn)
    isEDCReplicated
    contractDate
    profile {
      industry
      size
    }
  }
  jobs {
    openCount @include(if: $isLoggedIn)
    postedCount @include(if: $isLoggedIn)
    openJobs @include(if: $isLoggedIn) {
      id
      uid: id
      isPtcPrivate
      ciphertext
      title
      type
    }
  }
  avgHourlyJobsRate @include(if: $isLoggedIn) {
    amount
  }
}
fragment JobQualificationsFragment on JobQualifications {
  countries
  earnings
  groupRecno
  languages
  localDescription
  localFlexibilityDescription
  localMarket
  minJobSuccessScore
  minOdeskHours
  onSiteType
  prefEnglishSkill
  regions
  risingTalent
  shouldHavePortfolio
  states
  tests
  timezones
  type
  locationCheckRequired
  group {
    groupId
    groupLogo
    groupName
  }
  location {
    city
    country
    countryTimezone
    offsetFromUtcMillis
    state
    worldRegion
  }
  locations {
    id
    type
  }
  minHoursWeek @skip(if: $isLoggedIn)
  readyToStartToday {
    expiresAt
  }
}
fragment JobPubSimilarJobsFragment on PubSimilarJob {
  id
  ciphertext
  title
  description
  engagement
  durationLabel
  contractorTier
  type
  createdOn
  renewedOn
  amount {
    amount
  }
  maxAmount {
    amount
  }
  ontologySkills {
    id
    prefLabel
  }
  hourlyBudgetMin
  hourlyBudgetMax
}
query JobPubDetailsQuery($id: ID!, $isLoggedIn: Boolean!) {
  jobPubDetails(id: $id) {
    opening {
      ...JobPubOpeningFragment
    }
    qualifications {
      ...JobQualificationsFragment
    }
    buyer @include(if: $isLoggedIn) {
      ...JobPubBuyerInfoFragment
    }
    similarJobs {
      ...JobPubSimilarJobsFragment
    }
    buyerExtra @include(if: $isLoggedIn) {
      isPaymentMethodVerified
    }
  }
}"""

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
    if not tier:
        return "Not specified"
    
    tier_str = str(tier).strip().upper()
    if tier_str in ("1", "ENTRY"):
        return "Entry"
    elif tier_str in ("2", "INTERMEDIATE"):
        return "Intermediate"
    elif tier_str in ("3", "EXPERT"):
        return "Expert"
    return tier_str.replace("_", " ").title()

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

def format_proposal_count(item: dict) -> str:
    """Safely extracts the exact proposal range string provided by Upwork API."""
    if not item:
        return "Less than 5"

    job_inner = item.get("jobTile", {}).get("job", {}) or {}
    
    # Check all possible key locations for proposal tiers
    proposals_tier = (
        item.get("proposalsTier") 
        or job_inner.get("proposalsTier") 
        or item.get("proposalsTierLabel")
    )

    if not proposals_tier:
        return "Less than 5"

    # Case 1: Dict payload structure (e.g. {'label': '10 to 15'})
    if isinstance(proposals_tier, dict):
        tier_str = proposals_tier.get("label") or proposals_tier.get("name") or ""
    else:
        tier_str = str(proposals_tier)

    tier_clean = tier_str.strip()

    if not tier_clean or tier_clean.upper() == "N/A":
        return "Less than 5"

    # Exact format mapping for display
    return tier_clean


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
    Fetches Upwork job search results for a query string using guest headers.
    Handles 401 and empty data block token refreshes using auth_manager.
    Returns (jobs_list, updated_headers).
    """
    payload = json.loads(json.dumps(GRAPHQL_PAYLOAD))
    payload["variables"]["requestVariables"]["userQuery"] = query

    target_headers = auth_manager.get_search_headers(headers)
    target_headers["referer"] = f"https://www.upwork.com/nx/search/jobs/?q={requests.utils.quote(query)}"

    response = await post_with_exponential_backoff(UPWORK_URL, target_headers, payload)
    if not response:
        return [], headers

    if response.status_code == 401:
        print("❌ 401 Unauthorized hit in Search module. Refreshing guest session token...")
        new_cookies, new_auth = await asyncio.to_thread(auth_manager.refresh_tokens, force=True)
        if new_cookies and new_auth:
            target_headers = auth_manager.get_search_headers(headers)
            target_headers["referer"] = f"https://www.upwork.com/nx/search/jobs/?q={requests.utils.quote(query)}"
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
        print(f"⚠️ Upwork search returned empty data/error for '{query}'. Refreshing token...")
        new_cookies, new_auth = await asyncio.to_thread(auth_manager.refresh_tokens, force=True)
        if new_cookies and new_auth:
            target_headers = auth_manager.get_search_headers(headers)
            target_headers["referer"] = f"https://www.upwork.com/nx/search/jobs/?q={requests.utils.quote(query)}"
            response = await post_with_exponential_backoff(UPWORK_URL, target_headers, payload)
            if response:
                data = response.json()

    if "data" not in data or data["data"] is None:
        print(f"❌ Upwork returned empty data block for '{query}'. Skipping cycle.")
        print(f"🔍 [DEBUG RAW RESPONSE]: {data}") 
        return [], headers

    try:
        jobs = data["data"]["search"]["universalSearchNuxt"]["visitorJobSearchV1"]["results"]
        return jobs, target_headers
    except (KeyError, TypeError):
        return [], headers

async def fetch_job_details(ciphertext: str, headers: dict, auth_manager) -> dict | None:
    if not ciphertext:
        return None

    # isLoggedIn must be True for Upwork to return location, stats, and payment verification status
    payload = {
        "query": JOB_DETAILS_QUERY,
        "variables": {"id": ciphertext, "isLoggedIn": True}
    }
    details_headers = auth_manager.get_details_headers(headers)
    details_headers["referer"] = f"https://www.upwork.com/nx/search/jobs/details/{ciphertext}"

    try:
        response = await post_with_exponential_backoff(UPWORK_DETAILS_URL, details_headers, payload)
        if not response:
            print(f"⚠️ [Details] No response object for ciphertext {ciphertext}.")
            return None

        # Check if HTTP is 401 or if response has auth/permission errors
        is_auth_error = False
        body = None
        if response.status_code == 401:
            is_auth_error = True
        elif response.status_code == 200:
            try:
                body = response.json()
                if body and isinstance(body, dict):
                    errors = body.get("errors")
                    data = body.get("data")
                    # If GraphQL returned errors and we didn't get valid job details
                    if errors and (not data or not isinstance(data, dict) or not data.get("jobPubDetails")):
                        err_msg = str(errors).lower()
                        if any(term in err_msg for term in ["permission", "scope", "oauth2", "unauthorized", "token", "auth"]):
                            is_auth_error = True
            except Exception:
                pass

        if is_auth_error:
            print("⚠️ Unauthorized or permission restriction in job details. Refreshing token...")
            new_cookies, new_auth = await asyncio.to_thread(auth_manager.refresh_tokens, force=True)
            if new_cookies and new_auth:
                details_headers = auth_manager.get_details_headers(headers)
                response = await post_with_exponential_backoff(UPWORK_DETAILS_URL, details_headers, payload)
                if response and response.status_code == 200:
                    try:
                        body = response.json()
                    except Exception:
                        return None
                else:
                    return None
            else:
                return None

        if response.status_code != 200:
            print(f"❌ [Details] HTTP {response.status_code} for {ciphertext}")
            return None

        if not body:
            try:
                body = response.json()
            except Exception:
                return None

        if not body or not isinstance(body, dict):
            return None

        # Always try to extract data first
        data = body.get("data")
        if data and isinstance(data, dict):
            job_pub_details = data.get("jobPubDetails")
            if job_pub_details and isinstance(job_pub_details, dict):
                return job_pub_details

        # Log warning if token lacks permissions
        if body.get("errors") and not data:
            print("ℹ️ [Details] Upwork restricts detailed buyer stats for this guest token.")

    except Exception as e:
        print(f"⚠️ Secondary API Details Request Failed for {ciphertext}: {e}")
    return None

