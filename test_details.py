from curl_cffi import requests
import json

url = "https://www.upwork.com/api/graphql/v1?alias=gql-query-get-visitor-job-details"

headers = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "authorization": "Bearer oauth2v2_int_8132eb50393c19fe9f43efa8c0bf0662",
    "content-type": "application/json",
    "origin": "https://www.upwork.com",
    "referer": "https://www.upwork.com/nx/search/jobs/details/~022047808109244543596",
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "x-upwork-accept-language": "en-US",
}

# Paste your FULL cookie string from the -b '...' section of your curl command below,
# as ONE line, replacing the placeholder text between the quotes:
cookies_raw = "visitor_id=39.45.46.214.1784713260864000; enabled_ff=!CI12577UniversalSearch,!Fluid,!MP16400Air3Migration,!SSINavUser,!TranscendUIOn,!i18nGA,CI17409DarkModeUI,CmpLibOn,JPAir3,OTBnrOn,SSINavUserBpa,TONB2256Air3Migration,WP658TranscendOn,i18nOn; visitor_gql_token=oauth2v2_int_3b5e03e8ef4836049ee18fa9a815e655; country_code=PK; cf_clearance=KIW9ZJCw2ALONUg6efdqfaMMkndjeFQdvrK7EPt2aRQ-1784713278-1.2.1.1-ydgJDAvbKb9GZ9pLfhxWiWGfwAvwihkN9oCA2zUqqj.R0JHQyOadq7RONQab8hbx0tibounyN8xd68hf.7C7Hc3aygpXkLX7nCoNbK4SBqTWGiywxK48CNAI0O7gtVdaVTkrbiA4Xteq0txVflgVOjrFz0cVO1Z2AR0IsP0wWHfOZg7wvXVHWhMMTWQew5fTNQra42cudQORzfV4VLJmvjTq37..MGyazbkh1uxxbin07aEGEDV.xII2wMrI6pCEd3PmgZPi2q91Dc.TTSB8m2XEFj3bjVKnWs2C9MxDyPCUzhXpVfluObARHfHBTAnwoUbVLa87qJX8yCHxEM9D_GJCr1xIH.OlVVgJ9TdAOQASG7s7ZVKn47Nt7xNyb3ZAoEXdGzCYma8DGMT.ed69TMR08yF_5IIohKwPBmlvT_7zbzahGlh74GUrtypa2K0TNHTadIwBYNFM2pZuWO.1O6sn0pGeh5XlfK3e3wvCugQY0KMaC1YqSMAdGRGvHhfTN.V08KKqWl64yxN21c0jVQ; __cf_bm=29Sy3nrbSDujQGKRGznr3tvO9vcgMPjIgeA_6sKqFoc-1784713278.1526892-1.0.1.1-b9Youp4gDg6qvbcaJAQuoyadzpoTkZS5mWnovpI.9kg25Fz24f_1FtKKbMTj2PQUzfhebJdXR.2poQARWYlNaDb1uZnnM2WFLkJEm3qnjahRfJfFvfHxfX8992ycUh0o; UniversalSearchNuxt_vt=oauth2v2_int_8132eb50393c19fe9f43efa8c0bf0662"

headers["cookie"] = cookies_raw

with open("query.graphql", "r", encoding="utf-8") as f:
    query = f.read()

payload = {
    "query": query,
    "variables": {"id": "~022047808109244543596", "isLoggedIn": False}
}

resp = requests.post(url, headers=headers, json=payload, impersonate="chrome120", timeout=15)

print("STATUS:", resp.status_code)
print("BODY:")
print(resp.text[:3000])