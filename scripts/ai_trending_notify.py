#!/usr/bin/env python3
"""
ai_trending_notify.py

- Searches GitHub for AI-related repositories (keyword list) and collects candidate repos.
- Counts stars gained in the last 30 days and 180 days using the stargazers endpoint (Accept: vnd.github.v3.star+json).
- Produces two Top10 lists:
    1) Top10 by stars gained in last 180 days (半年内增长)
    2) Top10 by stars gained in last 30 days（最近1个月暴涨）
- Sends the results as a Markdown message to a DingTalk custom robot webhook.

Configuration (via environment variables):
- GITHUB_TOKEN: optional (Actions provides one automatically)
- DINDIN: required in Actions (repository secret named `dindin`) or DINGTALK_WEBHOOK for local testing
- DINGTALK_KEYWORD: optional, included in message header (default: "github")
- DINGTALK_AT_MOBILE: optional phone number to @ (e.g. "13996477307")
- MAX_CANDIDATES: optional integer, number of candidate repos to scan (default 120)
- RATE_SLEEP: optional float, seconds to sleep between paged GitHub requests (default 0.8)

Notes:
- The script tries to be conservative with GitHub API usage but scanning stargazers can be rate-heavy for large candidate sets.
- For higher throughput, consider using GitHub GraphQL to batch requests or narrow candidate set via topics.
"""

import os
import sys
import time
import json
import math
import datetime
import requests
from urllib.parse import quote_plus

# ---------------- Configuration ----------------
GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
# Prefer secret name 'dindin' in Actions; fallback to DINGTALK_WEBHOOK for local testing
DINGTALK_WEBHOOK = os.environ.get("DINDIN") or os.environ.get("DINGTALK_WEBHOOK", "")
DINGTALK_KEYWORD = os.environ.get("DINGTALK_KEYWORD", "github")
DINGTALK_AT_MOBILE = os.environ.get("DINGTALK_AT_MOBILE", "")
MAX_CANDIDATES = int(os.environ.get("MAX_CANDIDATES", "120"))
RATE_SLEEP = float(os.environ.get("RATE_SLEEP", "0.8"))

if not DINGTALK_WEBHOOK:
    print("ERROR: DingTalk webhook not configured. Set env DINDIN (preferred) or DINGTALK_WEBHOOK.", file=sys.stderr)
    sys.exit(2)

# Keywords used to discover candidate repositories. You can extend this list.
KEYWORDS = [
    "ai", "agent", "llm", "langchain", "copilot", "assistant", "autogen",
    "gpt", "chatbot", "transformers", "huggingface", "llama", "evals",
    "tool", "skill", "agentic", "model", "serving"
]

# ---------------- Helpers ----------------

def gh_headers(accept_starjson=False):
    headers = {"User-Agent": "ai-trending-bot"}
    headers["Accept"] = "application/vnd.github.v3.star+json" if accept_starjson else "application/vnd.github.v3+json"
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


def search_candidate_repos(max_candidates=120):
    """Search GitHub using keyword list, return deduplicated candidate repo metadata."""
    repos = {}
    per_page = 50
    for kw in KEYWORDS:
        q = f'{kw} in:name,description,readme'
        page = 1
        while len(repos) < max_candidates:
            url = f"{GITHUB_API}/search/repositories?q={quote_plus(q)}&sort=stars&order=desc&per_page={per_page}&page={page}"
            r = requests.get(url, headers=gh_headers())
            if r.status_code != 200:
                print(f"Warning: search {kw} returned {r.status_code}: {r.text}", file=sys.stderr)
                break
            data = r.json()
            items = data.get("items", [])
            if not items:
                break
            for it in items:
                full = it["full_name"]
                if full not in repos:
                    repos[full] = {
                        "full_name": full,
                        "owner": it["owner"]["login"],
                        "name": it["name"],
                        "html_url": it["html_url"],
                        "description": it.get("description") or "",
                        "stargazers_count": it.get("stargazers_count", 0),
                    }
                    if len(repos) >= max_candidates:
                        break
            if "next" not in r.links:
                break
            page += 1
            time.sleep(0.2)
        time.sleep(0.2)
    print(f"Collected {len(repos)} candidate repos")
    return list(repos.values())


def count_stars_since(owner, repo, since_dt):
    """Count number of stargazers with starred_at >= since_dt using paged stargazers endpoint.
    Returns integer count. Stops paging early when older starred_at are encountered.
    """
    per_page = 100
    page = 1
    count = 0
    while True:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/stargazers?per_page={per_page}&page={page}"
        r = requests.get(url, headers=gh_headers(accept_starjson=True))
        if r.status_code == 404:
            return 0
        if r.status_code != 200:
            print(f"Warning: stargazers {owner}/{repo} => {r.status_code}: {r.text}", file=sys.stderr)
            # If rate-limited, return current count; Actions will surface logs.
            return count
        arr = r.json()
        if not arr:
            break
        stop = False
        for entry in arr:
            starred_at = entry.get("starred_at")
            if not starred_at:
                continue
            try:
                st = datetime.datetime.strptime(starred_at, "%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                st = datetime.datetime.fromisoformat(starred_at.replace("Z", "+00:00")).replace(tzinfo=None)
            if st >= since_dt:
                count += 1
            else:
                stop = True
                break
        if stop:
            break
        if "next" not in r.links:
            break
        page += 1
        time.sleep(RATE_SLEEP)
    return count


# ---------------- Main flow ----------------

def build_and_send():
    now = datetime.datetime.utcnow()
    since_30 = now - datetime.timedelta(days=30)
    since_180 = now - datetime.timedelta(days=180)

    candidates = search_candidate_repos(MAX_CANDIDATES)
    results = []
    total = len(candidates)
    for i, repo in enumerate(candidates, 1):
        owner = repo["owner"]
        name = repo["name"]
        print(f"[{i}/{total}] Processing {repo['full_name']} (stars: {repo['stargazers_count']})")
        try:
            s30 = count_stars_since(owner, name, since_30)
            s180 = count_stars_since(owner, name, since_180)
        except Exception as e:
            print(f"Error counting stars for {repo['full_name']}: {e}", file=sys.stderr)
            s30 = s180 = 0
        repo.update({"stars_30d": s30, "stars_180d": s180})
        results.append(repo)
        # conservative sleep to avoid rate limits
        time.sleep(0.3)

    top_180 = sorted(results, key=lambda r: (r.get("stars_180d", 0), r.get("stargazers_count", 0)), reverse=True)[:10]
    top_30 = sorted(results, key=lambda r: (r.get("stars_30d", 0), r.get("stargazers_count", 0)), reverse=True)[:10]

    date_str = now.strftime("%Y-%m-%d")
    lines = [f"### 🚀 AI 开源工具推荐 — {date_str}  (keyword: {DINGTALK_KEYWORD})\n"]

    lines.append("#### 半年内增长 Top10（按 180 天内 star 增长）\n")
    for idx, r in enumerate(top_180, 1):
        lines.append(f"{idx}. [{r['full_name']}]({r['html_url']})  \n   {r['description']}\n   ⭐ 当前：{r['stargazers_count']}  |  半年↑：{r['stars_180d']}\n")

    lines.append("\n#### 最近 1 个月暴涨 Top10（按 30 天内 star 增长）\n")
    for idx, r in enumerate(top_30, 1):
        lines.append(f"{idx}. [{r['full_name']}]({r['html_url']})  \n   {r['description']}\n   ⭐ 当前：{r['stargazers_count']}  |  30天↑：{r['stars_30d']}\n")

    if DINGTALK_AT_MOBILE:
        lines.append(f"\n@{DINGTALK_AT_MOBILE}")

    md_text = "\n".join(lines)

    # also write results to file for future reference
    out_dir = "results"
    try:
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"ai_trending_{date_str}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"date": date_str, "top_180": top_180, "top_30": top_30}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: failed to write results file: {e}", file=sys.stderr)

    send_markdown(f"AI 开源工具推荐 {date_str}", md_text)


def send_markdown(title, text):
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"atMobiles": [DINGTALK_AT_MOBILE] if DINGTALK_AT_MOBILE else [], "isAtAll": False}
    }
    headers = {"Content-Type": "application/json;charset=utf-8"}
    try:
        r = requests.post(DINGTALK_WEBHOOK, json=payload, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"Failed to send to DingTalk: {r.status_code} {r.text}", file=sys.stderr)
        else:
            print("Sent to DingTalk:", r.text)
    except Exception as e:
        print(f"Error sending to DingTalk: {e}", file=sys.stderr)


if __name__ == '__main__':
    build_and_send()
