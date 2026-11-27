import os
import json
import hashlib
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from collectors import collect_all
from analyzer import analyze_jobs_hybrid

DB_PATH = "data/jobs.db"
OUT_PATH = "docs/data/market_intel.json"


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            source TEXT,
            region TEXT,
            title TEXT,
            company TEXT,
            location TEXT,
            work_mode TEXT,
            sector TEXT,
            experience_level TEXT,
            skills_json TEXT,
            salary_bdt_min INTEGER,
            salary_bdt_max INTEGER,
            salary_is_estimated INTEGER,
            raw_salary TEXT,
            posted_at TEXT,
            deadline TEXT,
            circular_url TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
    """)
    conn.commit()


def make_job_id(job: dict) -> str:
    key = f"{job['company'].lower().strip()}|{job['title'].lower().strip()}|{job['region'].lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def salary_tier(sal_max: int, region: str) -> str:
    if region == "Global Remote" and sal_max >= 120000:
        return "Remote USD (120k+ BDT eq.)"
    if sal_max >= 100000:
        return "100k+ BDT"
    if sal_max >= 50000:
        return "50k–100k BDT"
    if sal_max >= 25000:
        return "25k–50k BDT"
    return "<25k BDT"


def upsert_jobs(conn: sqlite3.Connection, jobs: list[dict], today: str):
    cur = conn.cursor()
    for j in jobs:
        jid = make_job_id(j)
        cur.execute("SELECT first_seen FROM jobs WHERE id = ?", (jid,))
        row = cur.fetchone()
        first_seen = row[0] if row else today
        cur.execute("""
            INSERT OR REPLACE INTO jobs (
                id, source, region, title, company, location, work_mode,
                sector, experience_level, skills_json, salary_bdt_min, salary_bdt_max,
                salary_is_estimated, raw_salary, posted_at, deadline, circular_url,
                first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            jid, j["source"], j["region"], j["title"], j["company"], j["location"],
            j["work_mode"], j["sector"], j["experience_level"], json.dumps(j["skills"]),
            j["salary_bdt_min"], j["salary_bdt_max"], int(j["salary_is_estimated"]),
            j["raw_salary"], j["posted_at"] or today, j["deadline"], j["circular_url"],
            first_seen, today,
        ))
    conn.commit()


def build_market_intel(conn: sqlite3.Connection, today_dt: datetime) -> dict:
    today = today_dt.strftime("%Y-%m-%d")
    d7 = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")

    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM jobs WHERE last_seen >= ?", (d30,)).fetchall()

    active_jobs = []
    skill_7d, skill_30d = Counter(), Counter()
    sector_counts = Counter()
    company_counts = Counter()
    tier_skills = defaultdict(Counter)
    tier_job_ids = defaultdict(list)

    for r in rows:
        skills = json.loads(r["skills_json"] or "[]")
        days_open = (today_dt - datetime.strptime(r["first_seen"], "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
        is_ghost = days_open >= 45
        tier = salary_tier(r["salary_bdt_max"], r["region"])

        job_obj = {
            "id": r["id"],
            "source": r["source"],
            "region": r["region"],
            "title": r["title"],
            "company": r["company"],
            "location": r["location"],
            "work_mode": r["work_mode"],
            "sector": r["sector"],
            "experience_level": r["experience_level"],
            "skills": skills,
            "salary_bdt_min": r["salary_bdt_min"],
            "salary_bdt_max": r["salary_bdt_max"],
            "salary_is_estimated": bool(r["salary_is_estimated"]),
            "salary_tier": tier,
            "posted_at": r["posted_at"],
            "deadline": r["deadline"],
            "circular_url": r["circular_url"],
            "is_ghost": is_ghost,
            "days_open": days_open,
        }
        active_jobs.append(job_obj)

        sector_counts[r["sector"]] += 1
        company_counts[r["company"]] += 1
        tier_job_ids[tier].append(r["id"])

        for s in skills:
            skill_30d[s] += 1
            if r["last_seen"] >= d7:
                skill_7d[s] += 1
            tier_skills[tier][s] += 1

    trending_skills = []
    for skill, c30 in skill_30d.most_common(25):
        c7 = skill_7d[skill]
        weekly_avg = max(c30 / 4.0, 0.5)
        velocity_pct = round(((c7 - weekly_avg) / weekly_avg) * 100)
        high_pay_count = sum(
            1 for j in active_jobs
            if skill in j["skills"] and j["salary_bdt_max"] >= 50000
        )
        trending_skills.append({
            "skill": skill,
            "count_30d": c30,
            "count_7d": c7,
            "velocity_pct": velocity_pct,
            "unlocks_50k_plus": high_pay_count,
        })

    tier_order = ["<25k BDT", "25k–50k BDT", "50k–100k BDT", "100k+ BDT", "Remote USD (120k+ BDT eq.)"]
    salary_unlock_matrix = []
    for t in tier_order:
        top_sk = [{"skill": k, "count": v} for k, v in tier_skills[t].most_common(8)]
        salary_unlock_matrix.append({
            "tier": t,
            "job_count": len(tier_job_ids[t]),
            "top_skills": top_sk,
        })

    hiring_pulse = [
        {"company": comp, "openings": cnt}
        for comp, cnt in company_counts.most_common(12)
        if comp not in ("Unknown", "Bangladesh Employer")
    ]

    return {
        "generated_at_bdt": (today_dt + timedelta(hours=6)).strftime("%Y-%m-%d %I:%M %p BDT"),
        "total_active_circulars": len(active_jobs),
        "sector_breakdown": dict(sector_counts.most_common()),
        "trending_skills": trending_skills,
        "salary_unlock_matrix": salary_unlock_matrix,
        "hiring_pulse": hiring_pulse,
        "circulars": sorted(active_jobs, key=lambda x: (x["posted_at"], x["salary_bdt_max"]), reverse=True),
    }


def main():
    os.makedirs("data", exist_ok=True)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")

    raw_jobs = collect_all()
    enriched_jobs = analyze_jobs_hybrid(raw_jobs)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    upsert_jobs(conn, enriched_jobs, today)
    intel = build_market_intel(conn, now_utc)
    conn.close()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(intel, f, indent=2, ensure_ascii=False)
    print(f"[SUCCESS] Exported {intel['total_active_circulars']} circulars to {OUT_PATH}")


if __name__ == "__main__":
    main()
