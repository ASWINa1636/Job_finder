from datetime import datetime, date, timezone
from urllib.parse import urlparse

PLATFORM_CATEGORIES = [
    "All platforms",
    "Greenhouse",
    "Lever.co",
    "Career Page",
    "Workday",
    "Ashby",
    "SmartRecruiters",
    "Remote OK",
    "Jobicy",
    "Arbeitnow",
    "Remotive"
]

ROLE_CATEGORIES = [
    "All Roles",
    "Backend Engineer",
    "Frontend Engineer",
    "Full Stack Engineer",
    "AI / ML / Data Science",
    "Data Engineer / Analytics",
    "DevOps / Cloud / SRE",
    "Mobile Developer",
    "QA / Automation / SDET",
    "Security / Cybersecurity",
    "Hardware / Embedded / IoT",
    "Other Engineering"
]

def parse_date(value):
    if not value:
        return None
    val_str = str(value).strip()
    try:
        if val_str.endswith("Z"):
            val_str = val_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(val_str)
        if dt.tzinfo:
            dt = dt.astimezone()
        return dt.date()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(val_str[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    # Handle numeric timestamps (e.g. Lever millisecond epoch timestamps)
    if val_str.isdigit():
        try:
            ts = int(val_str)
            if len(val_str) > 10:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except (ValueError, OSError):
            pass

    # Handle Workday relative date strings: "Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago"
    val_lower = val_str.lower()
    if "today" in val_lower:
        return date.today()
    if "yesterday" in val_lower:
        from datetime import timedelta
        return date.today() - timedelta(days=1)
    if "day" in val_lower:
        import re
        from datetime import timedelta
        m = re.search(r"(\d+)\+?\s*day", val_lower)
        if m:
            return date.today() - timedelta(days=int(m.group(1)))
    return None

def relative_date(value):
    d = parse_date(value)
    if not d:
        return "Posting date not provided"
    days = (date.today() - d).days
    if days < 0:
        return f"Date listed: {d.isoformat()}"
    if days == 0:
        return f"Posted today · {d.isoformat()}"
    if days == 1:
        return f"Posted yesterday · {d.isoformat()}"
    if days < 7:
        return f"Posted {days} days ago · {d.isoformat()}"
    if days < 30:
        weeks = days // 7
        return f"Posted {weeks} week{'s' if weeks != 1 else ''} ago · {d.isoformat()}"
    return f"Older listing ({days}d ago) · {d.isoformat()}"

def is_outdated_job(job, threshold_days=30):
    """
    Determine if a job posting is outdated (older than threshold_days or delisted).
    """
    if str(job.get("source_status") or "").lower() in ["delisted", "expired", "removed"]:
        return True
    d = parse_date(job.get("posted_at"))
    if d:
        return (date.today() - d).days > threshold_days
    return False

def is_missed_job(job, threshold_days=30):
    """
    Determine if a job is a 'missed opportunity':
    It is outdated (>threshold_days old or delisted) AND user never applied (status is New, Saved, or Interested).
    """
    if not is_outdated_job(job, threshold_days):
        return False
    status = str(job.get("status") or "New").strip()
    return status in ["New", "Saved", "Interested", ""]

def opportunity_status(job, threshold_days=30):
    """
    Returns a short classification tuple: (tag, label, color)
    """
    status = str(job.get("status") or "New").strip()
    outdated = is_outdated_job(job, threshold_days)

    if status in ["Applied", "Interview", "Offer"]:
        return ("in_progress", f"In Progress ({status})", "#16a34a")
    if status == "Rejected":
        return ("rejected", "Rejected", "#dc2626")
    if outdated:
        d = parse_date(job.get("posted_at"))
        days_str = f"{ (date.today() - d).days}d ago" if d else "Delisted"
        return ("missed", f"⚠️ Missed ({days_str})", "#b45309")
    return ("fresh", "🟢 Active & Fresh", "#2563eb")

def india_job(job):
    loc = str(job.get("location") or "").lower()
    india_terms = [
        "india", "bengaluru", "bangalore", "chennai", "hyderabad", "pune",
        "mumbai", "new delhi", "delhi", "gurugram", "gurgaon", "noida",
        "kolkata", "kochi", "cochin", "ahmedabad", "jaipur", "indore",
        "thiruvananthapuram", "remote - india", "india remote"
    ]
    return any(x in loc for x in india_terms)

def remote_job(job):
    loc = str(job.get("location") or "").lower()
    return any(x in loc for x in ["remote", "worldwide", "anywhere"])

def city_of(job):
    loc = str(job.get("location") or "").lower()
    cities = {
        "Chennai": ["chennai"],
        "Bengaluru": ["bengaluru", "bangalore"],
        "Hyderabad": ["hyderabad"],
        "Pune": ["pune"],
        "Mumbai": ["mumbai"],
        "Delhi NCR": ["delhi", "gurugram", "gurgaon", "noida"],
        "Kolkata": ["kolkata"],
        "Kochi": ["kochi", "cochin"],
        "Ahmedabad": ["ahmedabad"],
        "Jaipur": ["jaipur"],
        "Remote": ["remote", "worldwide", "anywhere"]
    }
    for name, terms in cities.items():
        if any(t in loc for t in terms):
            return name
    return "Other / Not specified"

def inferred_exp(job):
    exp = str(job.get("experience_level") or "Unknown")
    if exp != "Unknown":
        return exp
    text = (str(job.get("title", "")) + " " + str(job.get("description", ""))).lower()
    title = str(job.get("title", "")).lower()
    if any(x in title for x in ["intern", "internship", "trainee"]):
        return "Internship"
    if any(x in text for x in ["fresher", "new grad", "graduate program", "entry-level", "entry level", "0-1 year", "0–1 year"]):
        return "Fresher / 0–1 year"
    if any(x in text for x in ["5+ years", "5 years", "principal engineer", "staff engineer"]):
        return "5+ years"
    if any(x in text for x in ["3+ years", "3-5 years", "3–5 years", "senior"]):
        return "3–5 years"
    if any(x in text for x in ["1+ years", "2+ years", "1-3 years", "1–3 years"]):
        return "1–3 years"
    return "Unknown"

def inferred_type(job):
    val = str(job.get("job_type") or "Unknown")
    if val != "Unknown":
        return val
    text = (str(job.get("title", "")) + " " + str(job.get("employment_type", ""))).lower()
    if "intern" in text:
        return "Internship"
    if "part-time" in text or "part time" in text:
        return "Part-time"
    if "contract" in text:
        return "Contract"
    if "full-time" in text or "full time" in text:
        return "Full-time"
    return "Unknown"

def inferred_mode(job):
    val = str(job.get("work_mode") or "Unknown")
    if val != "Unknown":
        return val
    loc = str(job.get("location") or "").lower()
    if any(x in loc for x in ["remote", "worldwide", "anywhere"]):
        return "Remote"
    if "hybrid" in loc:
        return "Hybrid"
    return "On-site" if loc else "Unknown"

def inferred_role(job):
    """Infer the professional domain / role specialization from title and description."""
    title = str(job.get("title") or "").lower()
    text = (title + " " + str(job.get("description") or "")[:500]).lower()

    if any(x in title for x in ["full stack", "fullstack", "full-stack"]):
        return "Full Stack Engineer"
    if any(x in title for x in ["frontend", "front-end", "front end", "react", "ui engineer", "web developer"]):
        return "Frontend Engineer"
    if any(x in title for x in ["backend", "back-end", "back end", "python", "golang", "java developer", "api engineer"]):
        return "Backend Engineer"
    if any(x in title for x in ["data engineer", "etl", "big data", "spark", "pipeline", "analytics engineer"]):
        return "Data Engineer / Analytics"
    if any(x in title for x in ["machine learning", "ml ", "ai ", "data scientist", "deep learning", "nlp", "computer vision", "llm"]):
        return "AI / ML / Data Science"
    if any(x in title for x in ["devops", "sre", "site reliability", "cloud", "infrastructure", "platform engineer", "kubernetes"]):
        return "DevOps / Cloud / SRE"
    if any(x in title for x in ["android", "ios", "flutter", "mobile engineer", "react native", "swift"]):
        return "Mobile Developer"
    if any(x in title for x in ["qa", "quality", "test", "sdet", "automation engineer"]):
        return "QA / Automation / SDET"
    if any(x in title for x in ["security", "cyber", "infosec", "penetration", "soc"]):
        return "Security / Cybersecurity"
    if any(x in title for x in ["embedded", "firmware", "iot", "vlsi", "hardware", "verilog", "fpga", "robotics"]):
        return "Hardware / Embedded / IoT"

    if any(x in text for x in ["machine learning", "deep learning", "pytorch", "tensorflow", "llm"]):
        return "AI / ML / Data Science"
    if any(x in text for x in ["react", "next.js", "frontend", "html", "css", "vue"]):
        return "Frontend Engineer"
    if any(x in text for x in ["backend", "microservices", "api", "fastapi", "spring boot"]):
        return "Backend Engineer"

    return "Other Engineering"

def safe_salary(job):
    low, high = job.get("salary_min"), job.get("salary_max")
    currency = job.get("salary_currency") or "currency not specified"
    if low is not None and high is not None:
        return f"{currency} {low:,.0f}–{high:,.0f}"
    if low is not None:
        return f"{currency} {low:,.0f}+"
    if high is not None:
        return f"Up to {currency} {high:,.0f}"
    return "Not disclosed"

def inferred_platform(job):
    """
    Identifies the ATS or source platform hosting the job posting.
    Returns clean platform names: Greenhouse, Lever.co, Career Page, Workday, Ashby, SmartRecruiters, Remote OK, Jobicy, Arbeitnow, Remotive.
    """
    url = str(job.get("job_url") or "").strip().lower()
    source = str(job.get("source") or "").strip().lower()

    domain = ""
    path = ""
    if url:
        try:
            p = urlparse(url)
            domain = p.netloc.lower()
            path = p.path.lower()
        except Exception:
            domain = url

    # 1. ATS platforms
    if "greenhouse.io" in domain or "greenhouse" in source:
        return "Greenhouse"
    if "lever.co" in domain or "lever" in source:
        return "Lever.co"
    if "myworkdayjobs.com" in domain or "workday" in domain or "workday" in source:
        return "Workday"
    if "ashbyhq.com" in domain or "ashby" in domain or "ashby" in source:
        return "Ashby"
    if "smartrecruiters.com" in domain or "smartrecruiters" in source:
        return "SmartRecruiters"
    if "bamboohr.com" in domain or "bamboohr" in source:
        return "BambooHR"
    if "jobvite.com" in domain or "jobvite" in source:
        return "Jobvite"

    # 2. Public feeds & aggregators
    if "remoteok.com" in domain or "remoteok" in domain or "remote ok" in source:
        return "Remote OK"
    if "jobicy.com" in domain or "jobicy" in source:
        return "Jobicy"
    if "arbeitnow.com" in domain or "arbeitnow" in source:
        return "Arbeitnow"
    if "remotive.com" in domain or "remotive" in source:
        return "Remotive"

    # 3. Direct company career sites
    if any(x in domain for x in ["careers.", "jobs.", "workat.", "join."]) or any(x in path for x in ["/careers", "/jobs", "/career", "/openings"]):
        return "Career Page"

    if "career board" in source or "career page" in source:
        return "Career Page"

    # 4. Fallback cleanup
    if source:
        clean = source.replace(" public feed", "").replace(" public job feed", "").replace(" remote jobs feed", "").replace(" career board", "").strip().title()
        if clean:
            return clean

    return "Career Page"

def platform_badge_info(job):
    """
    Returns (platform_name, platform_category, icon)
    e.g. ("Greenhouse", "Direct ATS Career Board", "🏢")
    """
    plat = inferred_platform(job)
    ats_platforms = {"Greenhouse", "Lever.co", "Workday", "Ashby", "SmartRecruiters", "BambooHR", "Jobvite"}
    if plat in ats_platforms:
        return (plat, "Direct ATS Board", "🏢")
    elif plat == "Career Page":
        return (plat, "Company Career Portal", "🌐")
    else:
        return (plat, "Public Job Feed", "⚡")

