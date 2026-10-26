"""One-off generator for seeds/skills_seed.json (spec §9.7).

Run from the project root:  python scripts/_build_seed.py
Kept in the repo so the dictionary can be regenerated or extended deliberately.
"""

from __future__ import annotations

import json
from pathlib import Path

ENTRIES: list[dict] = []


def add(canonical, display, category, aliases=(), related=(), confusables=()):
    ENTRIES.append(
        {
            "canonical_name": canonical,
            "display_name": display,
            "category": category,
            "aliases": list(aliases),
            "related": list(related),
            "confusables": list(confusables),
        }
    )


# ── Languages ──────────────────────────────────────────────────────────────
add("python", "Python", "language", ["py", "python3"], ["django", "flask", "fastapi", "pandas"])
add("java", "Java", "language", ["java se", "java 8", "java 11", "java 17"],
    ["spring", "kotlin", "jvm"], ["javascript"])
add("javascript", "JavaScript", "language", ["js", "ecmascript", "es6", "es2015", "vanilla js"],
    ["typescript", "node.js", "react"], ["java"])
add("typescript", "TypeScript", "language", ["ts"], ["javascript", "angular", "react"])
add("c", "C", "language", ["ansi c", "c language"], ["c++", "embedded c"], ["c++", "c#"])
add("c++", "C++", "language", ["cpp", "c plus plus", "cplusplus"], ["c", "rust"], ["c", "c#"])
add("c#", "C#", "language", ["csharp", "c sharp", "c-sharp"], ["dotnet", ".net", "unity"], ["c", "c++"])
add("go", "Go", "language", ["golang"], [], [])
add("rust", "Rust", "language", ["rustlang"], ["c++", "wasm"])
add("ruby", "Ruby", "language", [], ["ruby on rails"])
add("php", "PHP", "language", ["php7", "php8"], ["laravel", "wordpress"])
add("swift", "Swift", "language", ["swiftui"], ["ios", "objective-c"])
add("kotlin", "Kotlin", "language", [], ["android", "java", "spring"])
add("scala", "Scala", "language", [], ["spark", "java"])
add("r", "R", "language", ["r language", "rstudio"], ["statistics", "pandas"])
add("bash", "Bash", "language", ["shell", "shell scripting", "sh", "zsh"], ["linux", "powershell"])
add("powershell", "PowerShell", "language", ["ps1", "pwsh"], ["bash", "windows"])
add("sql", "SQL", "language", ["ansi sql"], ["postgresql", "mysql", "sqlite"],
    ["mysql", "postgresql", "sqlite", "nosql"])
add("nosql", "NoSQL", "database", ["no sql"], ["mongodb", "cassandra"], ["sql"])
add("html", "HTML", "frontend", ["html5"], ["css", "javascript"])
add("css", "CSS", "frontend", ["css3", "scss", "sass"], ["html", "tailwind"])
add("matlab", "MATLAB", "language", [], ["simulink", "statistics"])
add("perl", "Perl", "language", [], ["bash"])
add("objective-c", "Objective-C", "language", ["objc"], ["ios", "swift"])
add("dart", "Dart", "language", [], ["flutter"])
add("elixir", "Elixir", "language", [], ["erlang", "phoenix"])
add("haskell", "Haskell", "language", [], ["functional programming"])
add("lua", "Lua", "language", [], ["unity"])
add("groovy", "Groovy", "language", [], ["jenkins", "gradle"])
add("vba", "VBA", "language", ["visual basic"], ["excel"])

# ── Backend frameworks ─────────────────────────────────────────────────────
add("django", "Django", "framework", ["django rest framework", "drf"],
    ["python", "flask", "fastapi"])
add("flask", "Flask", "framework", [], ["python", "django", "fastapi"])
add("fastapi", "FastAPI", "framework", [], ["python", "pydantic", "openapi"])
add("spring", "Spring", "framework", ["spring boot", "springboot"],
    ["java", "kotlin", "microservices"])
add("node.js", "Node.js", "backend", ["node", "nodejs"], ["javascript", "express", "npm"])
add("express", "Express", "framework", ["express.js", "expressjs"], ["node.js", "javascript"])
add("ruby on rails", "Ruby on Rails", "framework", ["rails", "ror"], ["ruby"])
add("laravel", "Laravel", "framework", [], ["php"])
add("asp.net", "ASP.NET", "framework", ["asp.net core", "dotnet core"], ["c#", "dotnet"])
add("dotnet", ".NET", "framework", [".net core", "dotnet"], ["c#", "asp.net"])
add("graphql", "GraphQL", "backend", ["apollo", "apollo graphql"], ["rest api", "apis"])
add("rest api", "REST API", "backend", ["rest", "restful", "restful api", "rest apis"],
    ["graphql", "apis"])
add("grpc", "gRPC", "backend", [], ["protobuf", "microservices"])
add("microservices", "Microservices", "backend", ["microservice architecture"],
    ["docker", "kubernetes", "rest api"])
add("celery", "Celery", "framework", [], ["python", "redis", "rabbitmq"])
add("websockets", "WebSockets", "backend", ["websocket"], ["rest api"])
add("gin", "Gin", "framework", ["gin-gonic"], ["go"])

# ── Data ───────────────────────────────────────────────────────────────────
add("pandas", "pandas", "data", ["python pandas"], ["numpy", "python", "data analysis"])
add("numpy", "NumPy", "data", ["numpy array"], ["pandas", "python"])
add("spark", "Apache Spark", "data", ["pyspark", "spark"], ["scala", "hadoop", "databricks"])
add("hadoop", "Hadoop", "data", ["hdfs", "mapreduce"], ["spark", "hive"])
add("kafka", "Apache Kafka", "data", ["kafka"], ["spark", "streaming"])
add("airflow", "Apache Airflow", "data", ["airflow"], ["etl", "python", "dbt"])
add("dbt", "dbt", "data", ["data build tool"], ["sql", "airflow", "snowflake"])
add("snowflake", "Snowflake", "data", [], ["dbt", "sql", "data warehouse"])
add("bigquery", "BigQuery", "data", ["google bigquery"], ["sql", "gcp"])
add("redshift", "Redshift", "data", ["amazon redshift"], ["sql", "aws"])
add("databricks", "Databricks", "data", [], ["spark", "delta lake"])
add("etl", "ETL", "data", ["elt", "extract transform load"], ["airflow", "dbt", "sql"])
add("data warehouse", "Data Warehousing", "data", ["data warehousing", "warehouse"],
    ["snowflake", "bigquery", "sql"])
add("tableau", "Tableau", "data", [], ["power bi", "data visualization"])
add("power bi", "Power BI", "data", ["powerbi"], ["tableau", "data visualization"])
add("looker", "Looker", "data", [], ["tableau", "bigquery"])
add("excel", "Excel", "tool", ["microsoft excel", "spreadsheets"], ["vba", "power bi"])
add("statistics", "Statistics", "data", ["statistical analysis", "stats"],
    ["r", "python", "machine learning"])
add("data analysis", "Data Analysis", "data", ["data analytics", "analytics"],
    ["pandas", "sql", "statistics"])
add("data visualization", "Data Visualization", "data", ["dataviz", "dashboards"],
    ["tableau", "power bi"])

# ── ML / AI ────────────────────────────────────────────────────────────────
# "artificial intelligence" must exist as an entry: machine learning declares it as a
# confusable, and confusables are validated for symmetry and existence (§9.7).
add("artificial intelligence", "Artificial Intelligence", "ml", ["ai"],
    ["machine learning", "deep learning"], ["machine learning"])
add("machine learning", "Machine Learning", "ml", ["ml"],
    ["python", "deep learning", "scikit-learn"], ["artificial intelligence"])
add("deep learning", "Deep Learning", "ml", ["dl"], ["pytorch", "tensorflow", "machine learning"])
add("pytorch", "PyTorch", "ml", ["torch"], ["deep learning", "python"])
add("tensorflow", "TensorFlow", "ml", ["tf", "keras"], ["deep learning", "python"])
add("scikit-learn", "scikit-learn", "ml", ["sklearn", "scikit learn"],
    ["python", "machine learning"])
add("nlp", "Natural Language Processing", "ml", ["natural language processing"],
    ["deep learning", "python"])
add("computer vision", "Computer Vision", "ml", ["opencv"], ["deep learning", "pytorch"])
add("llm", "Large Language Models", "ml",
    ["large language models", "llms", "genai", "generative ai"],
    ["nlp", "prompt engineering", "rag"])
add("prompt engineering", "Prompt Engineering", "ml", ["prompting"], ["llm", "nlp"])
add("rag", "Retrieval-Augmented Generation", "ml", ["retrieval augmented generation"],
    ["llm", "vector database"])
add("vector database", "Vector Database", "data",
    ["vector db", "pinecone", "weaviate", "pgvector"], ["rag", "embeddings"])
add("embeddings", "Embeddings", "ml", ["embedding models"], ["vector database", "nlp"])
add("mlops", "MLOps", "ml", ["ml ops"], ["machine learning", "docker", "kubernetes"])
add("langchain", "LangChain", "framework", [], ["llm", "python", "rag"])

# ── Databases ──────────────────────────────────────────────────────────────
add("postgresql", "PostgreSQL", "database", ["postgres", "psql", "pg", "postgres sql"],
    ["sql", "mysql", "sqlite"], ["mysql", "sqlite", "sql"])
add("mysql", "MySQL", "database", ["mariadb"], ["sql", "postgresql"],
    ["postgresql", "sqlite", "sql"])
add("sqlite", "SQLite", "database", [], ["sql", "postgresql"],
    ["postgresql", "mysql", "sql"])
add("mongodb", "MongoDB", "database", ["mongo"], ["redis", "nosql"])
add("redis", "Redis", "database", ["redis cache"], ["mongodb", "caching"])
add("elasticsearch", "Elasticsearch", "database", ["elastic search", "opensearch"],
    ["mongodb", "search"])
add("oracle", "Oracle Database", "database", ["oracle db", "pl/sql", "plsql"], ["sql"])
add("sql server", "SQL Server", "database", ["mssql", "microsoft sql server", "t-sql", "tsql"],
    ["sql", "dotnet"])
add("dynamodb", "DynamoDB", "database", ["amazon dynamodb"], ["aws", "nosql"])
add("cassandra", "Cassandra", "database", ["apache cassandra"], ["nosql"])
add("database design", "Database Design", "database",
    ["data modeling", "schema design", "normalization"], ["sql", "postgresql"])

# ── Cloud / DevOps ─────────────────────────────────────────────────────────
add("aws", "AWS", "cloud",
    ["amazon web services", "ec2", "s3", "lambda", "amazon aws"],
    ["cloud", "terraform", "docker"], ["azure", "gcp"])
add("azure", "Azure", "cloud", ["microsoft azure"], ["cloud", "aws", "dotnet"], ["aws", "gcp"])
add("gcp", "Google Cloud", "cloud", ["google cloud platform", "gcloud"],
    ["cloud", "bigquery", "aws"], ["aws", "azure"])
add("docker", "Docker", "devops", ["dockerfile", "containers", "containerization"],
    ["kubernetes", "devops"])
add("kubernetes", "Kubernetes", "devops", ["k8s", "kube", "kubernetes cluster"],
    # Note: no "docker" here, on purpose. Adjacency is directional: knowing Docker
    # does not imply orchestration, but knowing Kubernetes does imply containers
    # (see docker.related). This keeps the spec §11.5 worked example at 52.
    ["helm", "devops"])
add("helm", "Helm", "devops", ["helm charts"], ["kubernetes", "devops"])
add("terraform", "Terraform", "devops", ["iac", "infrastructure as code"],
    ["aws", "devops", "ansible"])
add("ansible", "Ansible", "devops", [], ["terraform", "devops", "linux"])
add("jenkins", "Jenkins", "devops", [], ["ci/cd", "devops"])
add("github actions", "GitHub Actions", "devops", ["gh actions"], ["ci/cd", "git"])
add("ci/cd", "CI/CD", "devops",
    ["cicd", "continuous integration", "continuous delivery", "continuous deployment"],
    ["jenkins", "docker", "devops"])
add("devops", "DevOps", "devops", ["devops practices"], ["docker", "kubernetes", "ci/cd"])
add("linux", "Linux", "tool", ["unix", "ubuntu", "debian", "centos", "rhel"], ["bash", "devops"])
add("git", "Git", "tool", ["gitlab", "bitbucket", "github", "version control"],
    ["github actions", "ci/cd"])
add("nginx", "Nginx", "devops", [], ["linux", "docker"])
add("prometheus", "Prometheus", "devops", [], ["kubernetes", "monitoring"])
add("grafana", "Grafana", "devops", [], ["prometheus", "monitoring"])
add("monitoring", "Monitoring", "devops", ["observability", "logging"],
    ["prometheus", "grafana"])
add("serverless", "Serverless", "cloud", ["lambda functions", "faas"], ["aws", "azure"])
add("cloud", "Cloud Computing", "cloud", ["cloud platform", "public cloud"],
    ["aws", "azure", "gcp"])
add("openstack", "OpenStack", "cloud", [], ["linux", "cloud"])
add("pulumi", "Pulumi", "devops", [], ["terraform", "iac"])

# ── Frontend ───────────────────────────────────────────────────────────────
add("react", "React", "frontend", ["react.js", "reactjs"],
    ["javascript", "redux", "next.js"], ["react native"])
add("react native", "React Native", "mobile", ["rn"], ["react", "javascript", "mobile"],
    ["react"])
add("angular", "Angular", "frontend", ["angularjs", "angular 2"], ["typescript", "rxjs"])
add("vue", "Vue.js", "frontend", ["vue.js", "vuejs", "nuxt"], ["javascript"])
add("next.js", "Next.js", "framework", ["nextjs", "next js"], ["react", "javascript"])
add("svelte", "Svelte", "frontend", ["sveltekit"], ["javascript"])
add("redux", "Redux", "frontend", ["redux toolkit"], ["react", "javascript"])
add("tailwind", "Tailwind CSS", "frontend", ["tailwindcss"], ["css"])
add("webpack", "Webpack", "tool", [], ["javascript"])
add("vite", "Vite", "tool", [], ["javascript"])
add("jquery", "jQuery", "frontend", [], ["javascript"])
add("responsive design", "Responsive Design", "frontend",
    ["responsive web design", "mobile responsive"], ["css", "html"])
add("accessibility", "Accessibility", "frontend", ["a11y", "wcag"], ["html", "css"])
add("ui", "UI Design", "frontend", ["user interface", "ui development"], ["ux", "figma"], ["ux"])
add("ux", "UX Design", "domain", ["user experience", "ux design"], ["ui", "figma"], ["ui"])
add("figma", "Figma", "tool", [], ["ui", "ux"])

# ── Testing / tooling ──────────────────────────────────────────────────────
add("jest", "Jest", "testing", ["jestjs"], ["javascript", "testing"])
add("cypress", "Cypress", "testing", [], ["e2e testing", "javascript"])
add("playwright", "Playwright", "testing", [], ["e2e testing", "automation"])
add("selenium", "Selenium", "testing", ["webdriver"], ["testing", "automation"])
add("vitest", "Vitest", "testing", [], ["javascript", "testing"])
add("pytest", "pytest", "testing", [], ["python", "testing"])
add("unit testing", "Unit Testing", "testing", ["unit tests", "tdd", "test driven development"],
    ["testing", "pytest"])
add("integration testing", "Integration Testing", "testing", [], ["testing"])
add("e2e testing", "End-to-End Testing", "testing", ["end to end testing", "e2e"],
    ["cypress", "playwright", "selenium"])
add("testing", "Software Testing", "testing", ["qa", "quality assurance", "automated testing"],
    ["unit testing", "pytest"])
add("jira", "Jira", "tool", ["atlassian jira"], ["agile", "confluence"])
add("confluence", "Confluence", "tool", [], ["jira", "documentation"])
add("agile", "Agile", "domain", ["scrum", "kanban", "agile methodology"],
    ["jira", "project management"])
add("project management", "Project Management", "domain",
    ["program management", "pmp"], ["agile", "leadership"])
add("documentation", "Technical Writing", "domain", ["technical writing", "docs"],
    ["confluence"])
add("openapi", "OpenAPI", "backend", ["swagger", "open api", "swagger ui"],
    ["rest api", "fastapi"])
add("pydantic", "Pydantic", "framework", [], ["python", "fastapi"])
add("postman", "Postman", "tool", [], ["rest api", "testing"])
add("docker compose", "Docker Compose", "devops", ["docker-compose"], ["docker", "devops"])
add("apis", "API Design", "backend", ["api", "api design", "api integration"],
    ["rest api", "graphql"])

# ── Domain / soft ──────────────────────────────────────────────────────────
add("leadership", "Leadership", "soft", ["team lead", "people management", "people leader"],
    ["communication", "project management"])
add("communication", "Communication", "soft", ["written communication", "verbal communication"],
    ["leadership"])
add("problem solving", "Problem Solving", "soft", ["analytical skills", "troubleshooting"],
    ["communication"])
add("collaboration", "Collaboration", "soft", ["teamwork", "cross-functional"],
    ["communication"])
add("time management", "Time Management", "soft", ["prioritization"], ["project management"])
add("presentation", "Presentations", "soft", ["public speaking", "presenting"])
add("customer service", "Customer Service", "soft", ["client support", "customer support"],
    ["communication"])
add("sales", "Sales", "domain", ["business development"], ["communication"])
add("marketing", "Marketing", "domain", ["digital marketing", "seo"], ["communication"])
add("finance", "Finance", "domain", ["financial analysis", "accounting"],
    ["excel", "statistics"])
add("healthcare", "Healthcare", "domain", ["health care", "clinical"])
add("security", "Security", "domain",
    ["cybersecurity", "information security", "infosec", "appsec"],
    ["owasp", "penetration testing"])
add("owasp", "OWASP", "domain", ["owasp top 10"], ["security"])
add("penetration testing", "Penetration Testing", "domain", ["pentesting", "pen testing"],
    ["security"])
add("oauth", "OAuth", "backend", ["oauth2", "oauth 2.0", "openid connect", "oidc"],
    ["security", "rest api"])
add("jwt", "JWT", "backend", ["json web token"], ["oauth", "security"])
add("encryption", "Encryption", "domain", ["cryptography", "tls", "ssl"], ["security"])
add("data privacy", "Data Privacy", "domain", ["gdpr", "hipaa", "privacy"], ["security"])
add("data structures", "Data Structures", "domain",
    ["algorithms", "data structures and algorithms", "dsa"], ["problem solving"])
add("system design", "System Design", "backend",
    ["distributed systems", "architecture design"], ["microservices", "scalability"])
add("scalability", "Scalability", "backend", ["high availability", "load balancing"],
    ["system design"])
add("caching", "Caching", "backend", ["cache"], ["redis", "performance optimization"])
add("performance optimization", "Performance Optimization", "backend",
    ["performance tuning", "optimization"], ["caching"])
add("technical leadership", "Technical Leadership", "soft", ["tech lead", "staff engineer"],
    ["leadership"])
add("mentoring", "Mentoring", "soft", ["mentorship", "coaching"], ["leadership"])
add("stakeholder management", "Stakeholder Management", "soft", ["stakeholders"],
    ["communication", "project management"])
add("product management", "Product Management", "domain",
    ["product owner", "product strategy"], ["agile"])
add("streaming", "Data Streaming", "data", ["event streaming", "stream processing"],
    ["kafka", "spark"])


def validate(entries: list[dict]) -> list[str]:
    """Rules from spec §9.7 — a bad dictionary must fail loudly, not degrade silently."""
    errors: list[str] = []
    canon = {e["canonical_name"] for e in entries}
    if len(canon) != len(entries):
        errors.append("duplicate canonical_name")

    alias_owner: dict[str, str] = {}
    for entry in entries:
        for alias in entry["aliases"]:
            if alias in alias_owner and alias_owner[alias] != entry["canonical_name"]:
                errors.append(
                    f"alias {alias!r} claimed by {alias_owner[alias]!r} and "
                    f"{entry['canonical_name']!r}"
                )
            alias_owner[alias] = entry["canonical_name"]

    for alias, owner in alias_owner.items():
        if alias in canon and alias != owner:
            errors.append(f"alias {alias!r} of {owner!r} collides with a canonical name")

    # confusables must be declared symmetrically
    declared = {(e["canonical_name"], c) for e in entries for c in e["confusables"]}
    for a, b in declared:
        if b in canon and (b, a) not in declared:
            errors.append(f"confusable {a!r} -> {b!r} is not declared symmetrically")
    return errors


def main() -> int:
    errors = validate(ENTRIES)
    if errors:
        print("Seed validation FAILED:")
        for err in errors[:20]:
            print("  -", err)
        return 1

    doc = {"seed_version": "2026.10.2", "skills": sorted(ENTRIES, key=lambda e: e["canonical_name"])}
    out = Path(__file__).resolve().parent.parent / "seeds" / "skills_seed.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    alias_count = sum(len(e["aliases"]) for e in ENTRIES)
    print(f"Wrote {out} — {len(ENTRIES)} skills, {alias_count} aliases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
