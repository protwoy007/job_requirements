import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "BDJobRadar/1.0 (Daily Market Intelligence Bot; +https://github.com)"
}
TIMEOUT = 20


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_deadline(text: str) -> str:
    t = (text or "").lower()
    m = re.search(r"\d{4}-\d{2}-\d{2}", t)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})\s+([a-z]{3})[a-z]*,?\s+(\d{4})", t)
    if m and m.group(2) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"([a-z]{3})[a-z]*\s+(\d{1,2}),?\s+(\d{4})", t)
    if m and m.group(1) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"
    return ""


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = BeautifulSoup(raw_html, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:2500]


def fetch_remotive(limit: int = 100) -> list[dict]:
    jobs = []
    try:
        r = requests.get(
            f"https://remotive.com/api/remote-jobs?limit={limit}",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            jobs.append({
                "source": "Remotive",
                "region": "Global Remote",
                "title": item.get("title", "").strip(),
                "company": item.get("company_name", "Unknown").strip(),
                "location": item.get("candidate_required_location", "Worldwide"),
                "work_mode": "Remote",
                "raw_salary": item.get("salary", "") or "",
                "category_hint": item.get("category", ""),
                "tags": item.get("tags", []) or [],
                "description": clean_html(item.get("description", "")),
                "posted_at": (item.get("publication_date") or "")[:10],
                "deadline": "",
                "circular_url": item.get("url", ""),
            })
    except Exception as e:
        print(f"[WARN] Remotive fetch failed: {e}")
    return jobs


def fetch_jobicy(count: int = 50) -> list[dict]:
    jobs = []
    try:
        r = requests.get(
            f"https://jobicy.com/api/v2/remote-jobs?count={count}",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        for item in r.json().get("jobs", []):
            sal_min = item.get("annualSalaryMin")
            sal_max = item.get("annualSalaryMax")
            raw_sal = f"${sal_min}-${sal_max}/yr" if sal_min and sal_max else ""
            jobs.append({
                "source": "Jobicy",
                "region": "Global Remote",
                "title": item.get("jobTitle", "").strip(),
                "company": item.get("companyName", "Unknown").strip(),
                "location": item.get("jobGeo", "Worldwide"),
                "work_mode": "Remote",
                "raw_salary": raw_sal,
                "category_hint": ", ".join(item.get("jobIndustry", [])),
                "tags": item.get("jobType", []) or [],
                "description": clean_html(item.get("jobDescription", "")),
                "posted_at": (item.get("pubDate") or "")[:10],
                "deadline": "",
                "circular_url": item.get("url", ""),
            })
    except Exception as e:
        print(f"[WARN] Jobicy fetch failed: {e}")
    return jobs


def fetch_remoteok(limit: int = 100) -> list[dict]:
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        for item in data[1 : limit + 1]:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            sal_min = item.get("salary_min") or 0
            sal_max = item.get("salary_max") or 0
            raw_sal = f"${sal_min}-${sal_max}/yr" if sal_min else ""
            jobs.append({
                "source": "RemoteOK",
                "region": "Global Remote",
                "title": item.get("position", "").strip(),
                "company": item.get("company", "Unknown").strip(),
                "location": item.get("location") or "Worldwide",
                "work_mode": "Remote",
                "raw_salary": raw_sal,
                "category_hint": "Tech / Remote",
                "tags": item.get("tags", []) or [],
                "description": clean_html(item.get("description", "")),
                "posted_at": (item.get("date") or "")[:10],
                "deadline": "",
                "circular_url": item.get("url", ""),
            })
    except Exception as e:
        print(f"[WARN] RemoteOK fetch failed: {e}")
    return jobs


def fetch_bdjobs_public(pages: int = 2) -> list[dict]:
    jobs = []
    urls = [
        ("Tech & IT", "https://jobs.bdjobs.com/jobsearch.asp?fcatId=8"),
        ("All Sectors", "https://jobs.bdjobs.com/jobsearch.asp"),
    ]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for hint, base_url in urls:
        for page in range(1, pages + 1):
            try:
                sep = "&" if "?" in base_url else "?"
                r = requests.get(f"{base_url}{sep}pg={page}", headers=HEADERS, timeout=TIMEOUT)
                if r.status_code != 200:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select(".norm-jobs-wrapper, .sout-jobs-wrapper")
                for card in cards:
                    title_el = card.select_one(".job-title-text a")
                    comp_el = card.select_one(".comp-name-text")
                    loc_el = card.select_one(".locon-text-d")
                    dead_el = card.select_one(".dead-text-d")
                    exp_el = card.select_one(".exp-text-d")
                    if not title_el:
                        continue
                    href = title_el.get("href", "")
                    full_url = href if href.startswith("http") else f"https://jobs.bdjobs.com/{href.lstrip('/')}"
                    desc = " | ".join(
                        el.get_text(" ", strip=True)
                        for el in [loc_el, exp_el, dead_el]
                        if el
                    )
                    jobs.append({
                        "source": "Bdjobs",
                        "region": "Bangladesh",
                        "title": title_el.get_text(" ", strip=True),
                        "company": comp_el.get_text(" ", strip=True) if comp_el else "Bangladesh Employer",
                        "location": loc_el.get_text(" ", strip=True) if loc_el else "Dhaka, Bangladesh",
                        "work_mode": "Hybrid" if "hybrid" in desc.lower() else ("Remote" if "remote" in desc.lower() else "Onsite"),
                        "raw_salary": "Negotiable",
                        "category_hint": hint,
                        "tags": [],
                        "description": desc,
                        "posted_at": "",
                        "deadline": parse_deadline(dead_el.get_text(" ", strip=True)) if dead_el else "",
                        "circular_url": full_url,
                    })
                time.sleep(1.2)
            except Exception as e:
                print(f"[WARN] Bdjobs ({hint} p{page}) skipped: {e}")
    return jobs


def fetch_skilljobs_bd() -> list[dict]:
    jobs = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        r = requests.get("https://skill.jobs/jobs", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return jobs
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href*='/job/']")[:30]:
            title = a.get_text(" ", strip=True)
            if len(title) < 4:
                continue
            href = a.get("href", "")
            full_url = href if href.startswith("http") else f"https://skill.jobs{href}"
            jobs.append({
                "source": "Skill.Jobs",
                "region": "Bangladesh",
                "title": title,
                "company": "Bangladesh Employer",
                "location": "Dhaka, Bangladesh",
                "work_mode": "Onsite",
                "raw_salary": "Negotiable",
                "category_hint": "Bangladesh Local",
                "tags": [],
                "description": title,
                "posted_at": "",
                "deadline": "",
                "circular_url": full_url,
            })
    except Exception as e:
        print(f"[WARN] Skill.Jobs skipped: {e}")
    return jobs


def collect_all() -> list[dict]:
    all_jobs = []
    all_jobs.extend(fetch_bdjobs_public(pages=2))
    all_jobs.extend(fetch_skilljobs_bd())
    all_jobs.extend(fetch_remotive(limit=100))
    all_jobs.extend(fetch_jobicy(count=50))
    all_jobs.extend(fetch_remoteok(limit=100))
    print(f"[INFO] Collected {len(all_jobs)} raw job circulars.")
    return all_jobs
