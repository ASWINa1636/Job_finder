import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Expanded list of 120+ modern technical skills and frameworks
TECH_SKILLS = [
    # Languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust",
    "kotlin", "swift", "scala", "php", "ruby", "bash", "shell", "sql", "r",

    # Web & Frontend
    "react", "next.js", "vue", "angular", "svelte", "html", "html5", "css", "css3",
    "tailwind", "tailwindcss", "redux", "graphql", "rest api", "vite", "webpack",

    # Backend & Frameworks
    "fastapi", "django", "flask", "node.js", "express", "spring", "spring boot",
    ".net", "asp.net", "gin", "microservices", "grpc", "websockets", "celery",

    # Databases & Caching
    "postgresql", "postgres", "mysql", "mongodb", "redis", "cassandra", "dynamodb",
    "sqlite", "elasticsearch", "neo4j", "supabase", "firebase",

    # Cloud & DevOps
    "docker", "kubernetes", "k8s", "aws", "azure", "gcp", "google cloud", "terraform",
    "ansible", "ci/cd", "github actions", "gitlab ci", "jenkins", "linux", "nginx",
    "serverless", "cloudformation", "helm", "argo cd",

    # Big Data & Data Engineering
    "spark", "apache spark", "kafka", "apache kafka", "airflow", "hadoop", "snowflake",
    "bigquery", "databricks", "dbt", "pandas", "numpy", "polars", "etl", "data pipeline",
    "power bi", "tableau", "excel", "data modeling",

    # AI, Machine Learning & Generative AI
    "machine learning", "deep learning", "pytorch", "tensorflow", "scikit-learn", "keras",
    "nlp", "natural language processing", "computer vision", "opencv", "hugging face",
    "transformers", "llm", "large language models", "rag", "langchain", "llamaindex",
    "faiss", "chromadb", "vector database", "fine-tuning", "vllm", "ollama",
    "generative ai", "prompt engineering",

    # Systems, Hardware & IoT
    "embedded systems", "iot", "arduino", "raspberry pi", "rtos", "verilog", "vhdl",
    "fpga", "vlsi", "circuit design", "electronics", "firmware", "robotics",

    # QA, Testing & SDET
    "testing", "unit testing", "pytest", "jest", "selenium", "playwright", "cypress",
    "automation", "qa", "sdet", "load testing", "postman",

    # Security & Core Concepts
    "cybersecurity", "infosec", "penetration testing", "owasp", "cryptography",
    "networking", "tcp/ip", "data structures", "algorithms", "dsa", "system design",
    "oop", "distributed systems", "agile", "scrum", "git"
]

def _normalise(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def extract_skills(text):
    haystack = _normalise(text)
    found = set()
    for skill in TECH_SKILLS:
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        if re.search(pattern, haystack):
            found.add(skill)
    return sorted(found)

def rank_jobs(resume_text, jobs):
    if not jobs:
        return []
    documents = [_normalise(resume_text)] + [
        _normalise(f"{j.get('title','')} {j.get('description','')} {j.get('company','')}")
        for j in jobs
    ]
    try:
        matrix = TfidfVectorizer(stop_words="english", max_features=35000, ngram_range=(1, 2)).fit_transform(documents)
        similarities = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    except ValueError:
        similarities = [0.0] * len(jobs)
    resume_skills = set(extract_skills(resume_text))
    ranked = []
    for idx, job in enumerate(jobs):
        job_skills = set(extract_skills(f"{job.get('title','')} {job.get('description','')}"))
        matched = sorted(resume_skills & job_skills)
        missing = sorted(job_skills - resume_skills)
        skill_score = len(matched) / max(1, len(job_skills))
        score = round((0.72 * float(similarities[idx]) + 0.28 * skill_score) * 100)
        ranked.append({
            **job,
            "match_score": min(100, score),
            "matched_skills": matched,
            "missing_skills": missing
        })
    return sorted(ranked, key=lambda x: x["match_score"], reverse=True)
