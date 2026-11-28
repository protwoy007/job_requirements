import os
import re
import json
from typing import List
from pydantic import BaseModel, Field

RATES = {"BDT": 1, "USD": 122, "EUR": 143, "GBP": 163}
USD_TO_BDT = RATES["USD"]

SECTORS = [
    "Tech & Software",
    "AI, Data & Analytics",
    "Cybersecurity & Cloud",
    "Business, Product & Marketing",
    "Banking & FinTech",
    "RMG & Textile",
    "Engineering & Energy",
    "Healthcare & Pharma",
    "Supply Chain & Logistics",
    "Govt, NGO & Others",
]

SKILL_DICTIONARY = {
    "AI / LLM APIs": [r"\bllm\b", r"\bopenai\b", r"\bgemini\b", r"\brag\b", r"\bagentic\b", r"generative ai", r"prompt engineering"],
    "AI Automation (n8n/Make)": [r"\bn8n\b", r"\bmake\.com\b", r"\bzapier\b", r"workflow automation"],
    "Python": [r"\bpython\b", r"\bdjango\b", r"\bfastapi\b", r"\bflask\b"],
    "JavaScript / TypeScript": [r"\bjavascript\b", r"\btypescript\b", r"\bnode\.?js\b"],
    "React / Next.js": [r"\breact\b", r"\bnext\.?js\b"],
    "Flutter / Mobile": [r"\bflutter\b", r"\breact native\b", r"\bandroid\b", r"\bkotlin\b", r"\bswift\b"],
    "Laravel / PHP": [r"\blaravel\b", r"\bphp\b"],
    "Java / Spring": [r"\bjava\b", r"\bspring boot\b"],
    "Docker / Kubernetes": [r"\bdocker\b", r"\bkubernetes\b", r"\bk8s\b", r"\bci/cd\b"],
    "AWS / Azure / GCP": [r"\baws\b", r"\bazure\b", r"\bgcp\b", r"cloud architecture"],
    "Cybersecurity / SOC": [r"\bcybersecurity\b", r"\bsoc\b", r"penetration test", r"\bsiem\b", r"\biso 27001\b", r"infosec"],
    "SQL & Databases": [r"\bsql\b", r"\bpostgresql\b", r"\bmysql\b", r"\bmongodb\b", r"\bredis\b"],
    "Power BI / Tableau": [r"power\s?bi", r"\btableau\b", r"\blooker", r"data visualization"],
    "Machine Learning": [r"machine learning", r"\bpytorch\b", r"\btensorflow\b", r"\bscikit\b", r"deep learning"],
    "UI/UX & Figma": [r"\bfigma\b", r"\bui/ux\b", r"product design", r"ux research"],
    "QA / Automation Testing": [r"\bselenium\b", r"\bplaywright\b", r"\bcypress\b", r"qa engineer", r"\bsqa"],
    "Product Management": [r"product manager", r"\bagile\b", r"\bscrum\b", r"\bjira\b", r"roadmap"],
    "SEO & Performance Ads": [r"\bseo\b", r"google ads", r"meta ads", r"digital marketing", r"performance marketing"],
    "SAP / ERP": [r"\bsap\b", r"\berp\b", r"oracle erp", r"supply chain"],
    "Financial Modeling / FinTech": [r"financial analysis", r"\bfintech\b", r"\bacc[a]?\b", r"\bcfa\b", r"risk management"],
    "RMG Merchandising / Lean": [r"merchandis", r"garments", r"textile", r"six sigma", r"ie engineer"],
    "AutoCAD / PLC / Civil": [r"\bautocad\b", r"\bplc\b", r"electrical", r"mechanical", r"civil engineer"],
}


class ParsedJob(BaseModel):
    idx: int = Field(description="Original index of the job in the batch")
    sector: str = Field(description=f"One of: {', '.join(SECTORS)}")
    experience_level: str = Field(description="Fresher, Junior (1-2y), Mid (3-5y), or Senior (5+y)")
    skills: List[str] = Field(description="Up to 6 concrete technical or domain skills")
    salary_bdt_min: int = Field(description="Monthly minimum salary in BDT (convert USD yearly to monthly BDT)")
    salary_bdt_max: int = Field(description="Monthly maximum salary in BDT")
    salary_is_estimated: bool = Field(description="True if salary was Negotiable or missing and had to be estimated")


class BatchResult(BaseModel):
    items: List[ParsedJob]


def detect_currency(raw_salary: str, region: str) -> str:
    s = (raw_salary or "").lower()
    if "€" in s or re.search(r"\beur\b", s):
        return "EUR"
    if "£" in s or re.search(r"\bgbp\b", s):
        return "GBP"
    if "$" in s or re.search(r"\busd\b", s):
        return "USD"
    if "৳" in s or re.search(r"\bbdt\b", s):
        return "BDT"
    return "USD" if region == "Global Remote" else "BDT"


def parse_explicit_salary_bdt(raw_salary: str, region: str) -> tuple[int, int, bool]:
    if not raw_salary or "negotiable" in raw_salary.lower():
        return 0, 0, True

    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{1,7}", raw_salary)]
    if not nums:
        return 0, 0, True

    low = nums[0]
    high = nums[1] if len(nums) > 1 else int(low * 1.25)
    lower_s = raw_salary.lower()

    if "k" in lower_s and low < 1000:
        low *= 1000
        high *= 1000

    cur = detect_currency(raw_salary, region)
    if "/yr" in lower_s or "year" in lower_s or "annual" in lower_s or (cur != "BDT" and low > 12000):
        low, high = low / 12, high / 12
    return int(low * RATES[cur]), int(high * RATES[cur]), False


def estimate_salary_offline(title: str, sector: str, exp: str, skills: list[str], region: str) -> tuple[int, int]:
    t = title.lower()
    base_min, base_max = 30000, 50000

    if sector in ("AI, Data & Analytics", "Cybersecurity & Cloud"):
        base_min, base_max = 55000, 95000
    elif sector == "Tech & Software":
        base_min, base_max = 45000, 80000
    elif sector in ("Banking & FinTech", "Business, Product & Marketing"):
        base_min, base_max = 40000, 75000
    elif sector in ("RMG & Textile", "Engineering & Energy", "Supply Chain & Logistics"):
        base_min, base_max = 35000, 65000

    if "product manager" in t:
        base_min, base_max = 85000, 130000
    elif "data analyst" in t:
        base_min, base_max = 55000, 85000
    elif "flutter" in t:
        base_min, base_max = 55000, 85000
    elif "ai" in t or "llm" in t or "automation" in t:
        base_min, base_max = 50000, 100000

    mult = {"Fresher": 0.55, "Junior (1-2y)": 0.85, "Mid (3-5y)": 1.15, "Senior (5+y)": 1.65}.get(exp, 1.0)
    est_min = int(base_min * mult)
    est_max = int(base_max * mult)

    premium_skills = {"AI / LLM APIs", "AWS / Azure / GCP", "Docker / Kubernetes", "Cybersecurity / SOC", "Machine Learning"}
    if any(s in premium_skills for s in skills):
        est_min = int(est_min * 1.15)
        est_max = int(est_max * 1.2)

    if region == "Global Remote":
        est_min = max(est_min * 2, 110000)
        est_max = max(est_max * 2, 240000)

    return round(est_min, -3), round(est_max, -3)


def analyze_offline(job: dict) -> dict:
    blob = f"{job['title']} {job['category_hint']} {' '.join(job.get('tags', []))} {job['description']}".lower()

    skills = [
        name for name, patterns in SKILL_DICTIONARY.items()
        if any(re.search(p, blob) for p in patterns)
    ][:6]

    if any(k in blob for k in ["cyber", "soc ", "infosec", "devops", "cloud", "aws", "kubernetes", "sre"]):
        sector = "Cybersecurity & Cloud"
    elif any(k in blob for k in ["ai ", "llm", "machine learning", "data analyst", "data scien", "power bi", "n8n"]):
        sector = "AI, Data & Analytics"
    elif any(k in blob for k in ["developer", "software", "engineer", "react", "python", "flutter", "laravel", "qa ", "frontend", "backend", "full stack"]):
        sector = "Tech & Software"
    elif any(k in blob for k in ["bank", "fintech", "credit", "audit", "finance", "accountant", "risk"]):
        sector = "Banking & FinTech"
    elif any(k in blob for k in ["garment", "textile", "merchandis", "rmg", "apparel"]):
        sector = "RMG & Textile"
    elif any(k in blob for k in ["marketing", "seo", "sales", "product manager", "business development", "growth"]):
        sector = "Business, Product & Marketing"
    elif any(k in blob for k in ["supply chain", "logistics", "procurement", "erp", "warehouse"]):
        sector = "Supply Chain & Logistics"
    elif any(k in blob for k in ["pharma", "medical", "doctor", "nurse", "healthcare"]):
        sector = "Healthcare & Pharma"
    elif any(k in blob for k in ["civil", "electrical", "mechanical", "solar", "energy", "autocad"]):
        sector = "Engineering & Energy"
    else:
        sector = "Govt, NGO & Others"

    if any(k in blob for k in ["senior", "lead", "principal", "architect", "staff", "head of", "5+ years", "6+ years"]):
        exp = "Senior (5+y)"
    elif any(k in blob for k in ["intern", "fresher", "trainee", "entry level", "graduate", "0-1 year"]):
        exp = "Fresher"
    elif any(k in blob for k in ["junior", "1-2 year", "1+ year", "associate"]):
        exp = "Junior (1-2y)"
    else:
        exp = "Mid (3-5y)"

    sal_min, sal_max, is_est = parse_explicit_salary_bdt(job.get("raw_salary", ""), job["region"])
    if is_est:
        sal_min, sal_max = estimate_salary_offline(job["title"], sector, exp, skills, job["region"])

    return {
        "sector": sector,
        "experience_level": exp,
        "skills": skills or ["Communication", "Domain Expertise"],
        "salary_bdt_min": sal_min,
        "salary_bdt_max": sal_max,
        "salary_is_estimated": is_est,
        "salary_currency": detect_currency(job.get("raw_salary", ""), job["region"]),
    }


def analyze_jobs_hybrid(raw_jobs: list[dict], batch_size: int = 15, max_ai_batches: int = 6) -> list[dict]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    enriched = [None] * len(raw_jobs)

    if api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            for b in range(0, min(len(raw_jobs), batch_size * max_ai_batches), batch_size):
                chunk = raw_jobs[b : b + batch_size]
                payload = [
                    {
                        "idx": b + i,
                        "region": j["region"],
                        "title": j["title"],
                        "company": j["company"],
                        "raw_salary": j["raw_salary"],
                        "hint": j["category_hint"],
                        "snippet": j["description"][:450],
                    }
                    for i, j in enumerate(chunk)
                ]
                prompt = (
                    "You are a Bangladesh & Global Remote job market analyst (2026). "
                    "For each job JSON item, extract structured fields. "
                    f"Use 1 USD = {RATES['USD']} BDT, 1 EUR = {RATES['EUR']} BDT, 1 GBP = {RATES['GBP']} BDT. Convert yearly salaries to monthly BDT. "
                    "If salary is Negotiable or missing, estimate realistic monthly BDT for 2026 and set salary_is_estimated=true. "
                    f"Jobs:\n{json.dumps(payload)}"
                )
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=BatchResult,
                        temperature=0.1,
                    ),
                )
                parsed = BatchResult.model_validate_json(resp.text)
                for item in parsed.items:
                    if 0 <= item.idx < len(raw_jobs):
                        enriched[item.idx] = item.model_dump(exclude={"idx"})
            print("[INFO] Gemini 2.5 Flash hybrid extraction completed.")
        except Exception as e:
            print(f"[WARN] Gemini API unavailable/limited ({e}); falling back to offline engine.")

    final_jobs = []
    for i, job in enumerate(raw_jobs):
        meta = enriched[i] if enriched[i] else analyze_offline(job)
        meta.setdefault("salary_currency", detect_currency(job["raw_salary"], job["region"]))
        lo, hi, est = parse_explicit_salary_bdt(job["raw_salary"], job["region"])
        if not est:
            meta.update(salary_bdt_min=lo, salary_bdt_max=hi, salary_is_estimated=False)
        merged = {**job, **meta}
        final_jobs.append(merged)
    return final_jobs
