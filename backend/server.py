from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import json
import asyncio
import httpx
import base64
import re
import secrets
import uuid  # FIX BUG-1: was missing, only uuid4 was imported
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from urllib.parse import urlencode
import time
import anthropic
import anyio  # for run_in_executor alternative (async thread offload)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

firebase_cred = credentials.Certificate(str(ROOT_DIR / 'firebase_config.json'))
if not firebase_admin._apps:
    firebase_admin.initialize_app(firebase_cred)

# Emergent Integrations
from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout, CheckoutSessionRequest
)

# Stripe (top-level import — FIX BUG-7)
try:
    import stripe as stripe_lib
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    logging.warning("stripe library not installed — enterprise payment routes disabled")

# Celery tasks (top-level import with graceful degradation — FIX BUG-8)
try:
    from tasks import analyze_organization as celery_analyze_organization
    CELERY_AVAILABLE = True
except ImportError:
    celery_analyze_organization = None
    CELERY_AVAILABLE = False
    logging.warning("Celery tasks module not available — enterprise analysis disabled")

# MongoDB
mongo_url = os.environ.get('MONGO_URL')
db_name = os.environ.get('DB_NAME')
if not mongo_url or not db_name:
    raise RuntimeError("CRITICAL: MONGO_URL and DB_NAME environment variables must be set.")

mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[db_name]

# FastAPI
app = FastAPI()
api_router = APIRouter(prefix="/api")
security = HTTPBearer(auto_error=False)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
CREDIT_PACKAGES = {
    "starter": {"price": 2.00, "credits": 5, "label": "$2 for 5 credits"},
    "popular": {"price": 5.00, "credits": 15, "label": "$5 for 15 credits"},
    "pro": {"price": 10.00, "credits": 35, "label": "$10 for 35 credits"},
}
GITHUB_CACHE_TTL = 3600


# ===== Models =====
class GenerateRequest(BaseModel):
    repo_url: str

class CheckoutRequest(BaseModel):
    package_id: str
    origin_url: str

class EditRequest(BaseModel):
    content: str

class GithubCallbackRequest(BaseModel):
    code: str


# ===== Helper Functions =====
async def check_repo_freshness(report: dict, owner: str, repo: str) -> dict:
    """Check if report needs upgrade based on age and new commits."""
    log_prefix = f"[freshness:{owner}/{repo}]"
    try:
        report_date = datetime.fromisoformat(report["generated_at"])
        days_old = (datetime.now(timezone.utc) - report_date).days

        if days_old < 30:
            logger.info(f"{log_prefix} Fresh ({days_old}d old) — no upgrade needed")
            return {
                "can_upgrade": False,
                "reason": f"Report is still fresh (updated {days_old} days ago)",
                "days_old": days_old
            }

        async with httpx.AsyncClient(timeout=10) as client:
            headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Gitopedia/1.0"}
            commits_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1",
                headers=headers
            )

            if commits_resp.status_code != 200:
                logger.warning(f"{log_prefix} GitHub commits fetch failed: {commits_resp.status_code}")
                return {"can_upgrade": False, "reason": "Could not fetch latest commits from GitHub"}

            commits = commits_resp.json()
            if not commits:
                return {"can_upgrade": False, "reason": "No commits found"}

            latest_commit = commits[0]
            latest_commit_sha = latest_commit["sha"]
            latest_commit_date = latest_commit["commit"]["author"]["date"]

            report_commit_sha = report.get("repo_last_commit_sha")
            if latest_commit_sha == report_commit_sha:
                logger.info(f"{log_prefix} No new commits since last report")
                return {
                    "can_upgrade": False,
                    "reason": "No new commits since last report",
                    "days_old": days_old
                }

            compare_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/compare/{report_commit_sha}...{latest_commit_sha}",
                headers=headers
            )

            new_commits_count = 0
            if compare_resp.status_code == 200:
                new_commits_count = compare_resp.json().get("total_commits", 0)

            logger.info(f"{log_prefix} Upgradeable — {days_old}d old, {new_commits_count} new commits")
            return {
                "can_upgrade": True,
                "reason": f"Report is {days_old} days old with {new_commits_count} new commits",
                "days_old": days_old,
                "new_commits_count": new_commits_count,
                "latest_commit_date": latest_commit_date,
                "latest_commit_sha": latest_commit_sha
            }

    except Exception as e:
        logger.error(f"{log_prefix} Error checking freshness: {e}")
        return {"can_upgrade": False, "reason": "Error checking repository status"}


# ===== Auth Dependencies =====

def _verify_firebase_token_sync(token: str):
    """Synchronous Firebase verification — runs in thread pool. FIX BUG-3."""
    return firebase_auth.verify_id_token(token)


async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not creds:
        raise HTTPException(401, "Authentication required")
    try:
        # FIX BUG-3: offload blocking Firebase SDK call to thread pool
        decoded = await anyio.to_thread.run_sync(
            _verify_firebase_token_sync, creds.credentials
        )
        return decoded
    except Exception as e:
        logger.warning(f"Auth failure: {type(e).__name__}: {e}")
        raise HTTPException(401, "Invalid authentication token")


async def get_optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not creds:
        return None
    try:
        return await anyio.to_thread.run_sync(_verify_firebase_token_sync, creds.credentials)
    except Exception:
        return None


# ===== GitHub API =====
def parse_repo_url(url: str):
    patterns = [
        r'github\.com/([^/]+)/([^/\s?#]+)',
        r'^([^/\s]+)/([^/\s]+)$',
    ]
    for pattern in patterns:
        match = re.search(pattern, url.strip().rstrip('/'))
        if match:
            return match.group(1), match.group(2).replace('.git', '')
    raise ValueError("Invalid GitHub repository URL")


async def fetch_github_data(owner: str, repo: str, fast_mode: bool = True) -> dict:
    """Fetch GitHub data with caching."""
    log_prefix = f"[github:{owner}/{repo}]"
    cache_key = f"{owner}/{repo}"
    cached = await db.github_cache.find_one({"repo_full_name": cache_key}, {"_id": 0})
    if cached:
        try:
            cached_time = datetime.fromisoformat(cached["fetched_at"])
            age_s = (datetime.now(timezone.utc) - cached_time).total_seconds()
            if age_s < GITHUB_CACHE_TTL:
                logger.info(f"{log_prefix} Cache hit ({int(age_s)}s old)")
                return cached["data"]
            logger.info(f"{log_prefix} Cache stale ({int(age_s)}s old), refreshing")
        except Exception:
            pass

    logger.info(f"{log_prefix} Fetching from GitHub API")
    # NOTE: Add Authorization header here for authenticated requests (5000 req/hr vs 60)
    # e.g., headers["Authorization"] = f"Bearer {os.environ.get('GITHUB_TOKEN')}"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Gitopedia/1.0"}

    async with httpx.AsyncClient(timeout=30) as client:
        repo_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        if repo_resp.status_code == 404:
            raise HTTPException(404, "Repository not found. It may be private or doesn't exist.")
        if repo_resp.status_code == 403:
            raise HTTPException(429, "GitHub API rate limit exceeded. Please try again later.")
        if repo_resp.status_code != 200:
            raise HTTPException(502, f"GitHub API error: {repo_resp.status_code}")

        repo_info = repo_resp.json()
        if repo_info.get("private"):
            raise HTTPException(400, "Private repositories are not supported yet.")

        default_branch = repo_info.get("default_branch", "main")

        readme_resp, tree_resp, langs_resp, contribs_resp, commits_resp = await asyncio.gather(
            client.get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers=headers),
            client.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1", headers=headers),
            client.get(f"https://api.github.com/repos/{owner}/{repo}/languages", headers=headers),
            client.get(f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=10", headers=headers),
            client.get(f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=10", headers=headers),
            return_exceptions=True,
        )

        readme_content = ""
        if not isinstance(readme_resp, Exception) and readme_resp.status_code == 200:
            try:
                raw = readme_resp.json()
                readme_content = base64.b64decode(raw.get("content", "")).decode("utf-8", errors="replace")
                if len(readme_content) > 10000:
                    readme_content = readme_content[:10000] + "\n\n[... README truncated ...]"
            except Exception as e:
                logger.warning(f"{log_prefix} README decode error: {e}")

        file_tree = []
        if not isinstance(tree_resp, Exception) and tree_resp.status_code == 200:
            exclude_patterns = [
                'node_modules/', '.git/', 'dist/', 'build/', 'target/', 'vendor/',
                '.next/', '.nuxt/', 'out/', 'coverage/', '.cache/', '__pycache__/',
                'venv/', 'env/', '.venv/', 'site-packages/', 'pkg/', 'bin/',
                '.DS_Store', 'thumbs.db', '.idea/', '.vscode/', '.terraform/',
                'bower_components/', 'jspm_packages/', '.gradle/', '.mvn/', 'test/',
                'tests/', 'spec/', '__tests__/', '.pytest_cache/', 'public/static/'
            ]
            binary_extensions = [
                '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.svg', '.webp',
                '.mp4', '.avi', '.mov', '.wmv', '.flv', '.pdf', '.zip', '.tar',
                '.gz', '.rar', '.7z', '.exe', '.dll', '.so', '.dylib', '.jar',
                '.war', '.ear', '.woff', '.woff2', '.ttf', '.eot', '.otf', '.map'
            ]
            max_files = 300 if fast_mode else 1000
            for item in (tree_resp.json().get("tree") or [])[:max_files]:
                path = item.get("path", "")
                if any(pattern in path for pattern in exclude_patterns):
                    continue
                if any(path.lower().endswith(ext) for ext in binary_extensions):
                    continue
                if item.get("size", 0) > 1048576:
                    file_tree.append(f"{path} (large file)")
                else:
                    file_tree.append(path)

        languages = {}
        if not isinstance(langs_resp, Exception) and langs_resp.status_code == 200:
            languages = langs_resp.json()

        contributors = []
        if not isinstance(contribs_resp, Exception) and contribs_resp.status_code == 200:
            for c in (contribs_resp.json() or [])[:10]:
                contributors.append({"login": c.get("login"), "contributions": c.get("contributions")})

        recent_commits = []
        if not isinstance(commits_resp, Exception) and commits_resp.status_code == 200:
            for c in (commits_resp.json() or [])[:10]:
                commit = c.get("commit", {})
                recent_commits.append({
                    "sha": c.get("sha", ""),
                    "message": commit.get("message", "")[:200],
                    "author": commit.get("author", {}).get("name"),
                    "date": commit.get("author", {}).get("date"),
                })

        config_files = {}
        key_files = [
            "package.json", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml",
            "Dockerfile", "docker-compose.yml", "Makefile", "tsconfig.json", "pyproject.toml"
        ]
        for filepath in key_files:
            try:
                resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{filepath}", headers=headers
                )
                if resp.status_code == 200:
                    content_data = resp.json()
                    if content_data.get("size", 0) <= 100000:
                        content = base64.b64decode(content_data.get("content", "")).decode("utf-8", errors="replace")
                        config_files[filepath] = content[:5000]
            except Exception as e:
                logger.warning(f"{log_prefix} Error fetching config {filepath}: {e}")

        data = {
            "repo_info": {
                "full_name": repo_info.get("full_name"),
                "name": repo_info.get("name"),
                "description": repo_info.get("description", ""),
                "language": repo_info.get("language"),
                "stargazers_count": repo_info.get("stargazers_count", 0),
                "forks_count": repo_info.get("forks_count", 0),
                "open_issues_count": repo_info.get("open_issues_count", 0),
                "created_at": repo_info.get("created_at"),
                "pushed_at": repo_info.get("pushed_at"),
                "default_branch": default_branch,
                "license": repo_info.get("license", {}).get("spdx_id") if repo_info.get("license") else None,
                "topics": repo_info.get("topics", []),
                "html_url": repo_info.get("html_url"),
                "watchers_count": repo_info.get("watchers_count", 0),
                "size": repo_info.get("size", 0),
            },
            "readme": readme_content,
            "file_tree": file_tree,
            "languages": languages,
            "contributors": contributors,
            "recent_commits": recent_commits,
            "config_files": config_files,
        }

    logger.info(f"{log_prefix} Data fetched — {len(file_tree)} files, {len(config_files)} configs")
    await db.github_cache.update_one(
        {"repo_full_name": cache_key},
        {"$set": {"repo_full_name": cache_key, "data": data, "fetched_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return data


# ===== LLM Report Generation =====
def build_report_prompt(data: dict) -> str:
    repo = data["repo_info"]
    languages_str = "\n".join([f"- {lang}: {bc} bytes" for lang, bc in data["languages"].items()])
    tree_str = "\n".join(data["file_tree"][:150])
    if len(data["file_tree"]) > 150:
        tree_str += f"\n... and {len(data['file_tree']) - 150} more files"
    configs_str = ""
    for fp, content in data["config_files"].items():
        configs_str += f"\n### {fp}\n```\n{content}\n```\n"
    contribs_str = "\n".join([f"- {c['login']}: {c['contributions']} contributions" for c in data["contributors"]])
    commits_str = "\n".join([
        f"- [{c['date'][:10] if c['date'] else 'N/A'}] {c['author']}: {c['message']}"
        for c in data["recent_commits"]
    ])

    has_db_schema = False
    db_hints = []
    for fp in data["file_tree"]:
        fp_lower = fp.lower()
        if any(kw in fp_lower for kw in ["migration", "schema", "models.py", "model.go", "entity", "prisma", "drizzle", ".sql", "typeorm", "sequelize", "alembic", "knex"]):
            has_db_schema = True
            db_hints.append(fp)

    db_section = ""
    if has_db_schema:
        db_section = f"""
## Database Schema
The repository contains database-related files: {', '.join(db_hints[:15])}
Analyze these and provide a Mermaid ER diagram showing the database schema with entities, their key attributes, and relationships:

```mermaid
erDiagram
    ENTITY1 {{
        type field1 PK
        type field2
    }}
    ENTITY1 ||--o{{ ENTITY2 : "relationship"
```
Include all tables/models you can identify from the file structure and config files. Show primary keys (PK), foreign keys (FK), and relationship cardinality."""
    else:
        db_section = """
## Database Schema
Analyze if there are any database dependencies (e.g., databases listed in config files, ORM imports, connection strings). If found, describe the likely schema. If no database is detected, state "No database schema detected in this repository." """

    return f"""You are performing a deep technical analysis of a GitHub repository. Generate an exhaustive, expert-level Markdown report. This report should be useful to a senior engineer joining the project for the first time.

## RAW DATA

### Repository Metadata
- Full Name: {repo['full_name']}
- Description: {repo['description'] or 'No description provided'}
- Primary Language: {repo['language'] or 'N/A'}
- Stars: {repo['stargazers_count']} | Forks: {repo['forks_count']} | Open Issues: {repo['open_issues_count']} | Watchers: {repo.get('watchers_count', 'N/A')}
- Created: {repo['created_at']} | Last Push: {repo['pushed_at']}
- Default Branch: {repo['default_branch']} | License: {repo['license'] or 'Not specified'}
- Topics: {', '.join(repo['topics']) if repo['topics'] else 'None'}
- Repository Size: {repo['size']} KB

### Languages Breakdown
{languages_str or 'No language data available'}

### Complete File Tree
{tree_str or 'Unable to retrieve file structure'}

### README Content
{data['readme'] or 'No README found'}

### Configuration Files
{configs_str or 'No configuration files found'}

### Top Contributors
{contribs_str or 'No contributor data available'}

### Recent Commits (Last 10)
{commits_str or 'No recent commit data'}

---

## REPORT INSTRUCTIONS

Generate a comprehensive report with EXACTLY these sections in order. Start directly with the first heading. Use Mermaid diagram syntax where specified.

## Overview
4-6 sentences providing a thorough summary: what the project does, who it's for, what problem it solves, its maturity level, and where it fits in the ecosystem. Mention notable adoption metrics if the star/fork count is significant.

## Tech Stack
A detailed markdown table with columns: **Layer** | **Technology** | **Version** (if detectable) | **Purpose**
Include ALL layers you can identify: Language(s), Runtime, Framework(s), Database(s), ORM/ODM, Authentication, API Protocol, Frontend, CSS/Styling, State Management, Testing, CI/CD, Build Tools, Package Manager, Linting/Formatting, Containerization, Monitoring/Logging, Documentation tools. Only include what is confirmed by the data.

## Directory Structure
Provide a detailed **ASCII directory tree** showing the project's folder structure. Include key files and annotate the purpose of each major directory with inline comments:

```
project-root/
├── src/                    # Main source code
│   ├── api/                # API route handlers
│   ├── models/             # Data models
│   └── utils/              # Shared utilities
├── tests/                  # Test suites
├── config/                 # Configuration
├── docs/                   # Documentation
├── Dockerfile              # Container definition
└── package.json            # Dependencies
```

After the tree, provide a prose explanation of the architecture implied by the directory layout.

## Architecture & Design
Deep analysis of the system architecture. Identify and explain:
- Architecture pattern (monolith, microservices, modular monolith, serverless, etc.)
- Design patterns used (MVC, CQRS, event sourcing, repository pattern, etc.)
- Layer separation and boundaries
- Key abstractions and interfaces

Include a Mermaid flowchart showing the high-level system architecture:

```mermaid
graph TD
    A[Component] -->|protocol| B[Component]
    B --> C[Component]
```

## Service Communication & Dependencies
Detailed analysis of how components interact:
- Internal service calls (function calls, gRPC, REST, GraphQL)
- External API integrations
- Message queues or event buses
- Shared state or databases
- Authentication/authorization flow

Include a Mermaid sequence diagram showing a key workflow:

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Service
    participant DB
    Client->>API: Request
    API->>Service: Process
    Service->>DB: Query
    DB-->>Service: Result
    Service-->>API: Response
    API-->>Client: Response
```
{db_section}

## Infrastructure & Deployment
Detailed deployment analysis:
- Container setup (Docker, docker-compose configurations)
- CI/CD pipeline (GitHub Actions, GitLab CI, etc.)
- Cloud provider hints (AWS, GCP, Azure, Vercel, etc.)
- Environment configuration management
- Scaling considerations visible in the codebase

## Development Workflow
Step-by-step guide to run this project locally based on the config files:
1. Prerequisites (runtime versions, tools needed)
2. Installation steps
3. Environment setup
4. Running the application
5. Running tests
6. Common development tasks

## Security Considerations
Analyze security aspects visible in the codebase:
- Authentication/authorization mechanisms
- Secret management approach
- Input validation patterns
- Dependency security (known patterns)
- CORS, CSP, or other security headers

## Dependency Analysis
Analyze the project's dependency footprint:
- Count of direct vs transitive dependencies
- Notable/heavyweight dependencies and why they're likely used
- Potential dependency concerns (very old, deprecated, or risky packages)
- Dependency update strategy (lockfiles, version pinning)

## Code Quality & Patterns
Observations about code quality:
- Code organization patterns
- Error handling approach
- Logging strategy
- Type safety (TypeScript strict mode, type hints, etc.)
- Test coverage indicators (test file presence, test frameworks)

## Key Observations
7-10 bullet points covering the most important things a new developer should know, including:
- Architecture decisions and their tradeoffs
- Potential scaling bottlenecks
- Areas of technical debt (if visible)
- Strengths of the codebase
- Unusual or noteworthy patterns

## Repo Health
A detailed markdown table: **Metric** | **Value** | **Assessment**
Include: Stars, Forks, Open Issues, Issue-to-Star Ratio, Last Push Date, Days Since Last Push, License, Primary Language, Number of Languages, Contributors Count, Repository Size, Topic Tags.

CRITICAL RULES:
- Only include facts supported by the provided data. NEVER fabricate or guess.
- For Mermaid diagrams: use VALID Mermaid syntax. Keep diagrams clean and readable. Use descriptive node labels.
- In Mermaid diagrams: do NOT use parentheses () inside node labels. Use square brackets [] for nodes.
- If a section cannot be determined from the data, write a brief note explaining why and what data would be needed.
- Use proper Markdown formatting throughout: tables, bullet points, code blocks, bold for emphasis.
- Be thorough and detailed — this report should be genuinely useful for onboarding.
- Start directly with ## Overview. No preamble, no introduction."""


async def stream_llm_report(data: dict):
    """
    FIX BUG-2: Stream LLM tokens directly instead of waiting for full completion.

    Uses the Anthropic streaming API so that:
    - First token arrives in ~1-3 seconds (SSE connection stays alive)
    - Tokens are yielded as SSE 'content' events in real-time
    - No keepalive pings needed — the stream itself is the keepalive
    - No asyncio.CancelledError from proxy/ingress timeouts

    Yields: (chunk: str) for content chunks, raises on error.
    Also returns the full accumulated text at the end via `full_text`.
    """
    prompt = build_report_prompt(data)
    system_msg = (
        "You are a senior software architect. Analyze this repository and create a concise, "
        "technical report with key insights, architecture overview, tech stack, and directory structure. "
        "Include Mermaid diagrams where helpful. Be direct and actionable."
    )
    repo_name = data["repo_info"].get("full_name", "unknown")
    logger.info(f"[LLM:{repo_name}] Starting streaming generation (~{len(prompt)//4} prompt tokens est.)")

    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    if anthropic_key:
        client = anthropic.AsyncAnthropic(api_key=anthropic_key, timeout=300.0)
        full_text = []
        start = time.time()

        # Try Haiku first for speed (FIX BUG-2: streaming, not batch)
        try:
            logger.info(f"[LLM:{repo_name}] Streaming via claude-3-haiku (fast mode)")
            async with client.messages.stream(
                model="claude-3-haiku-20240307",
                max_tokens=4096,
                system=system_msg,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text_chunk in stream.text_stream:
                    full_text.append(text_chunk)
                    yield text_chunk

            elapsed = time.time() - start
            total_chars = sum(len(c) for c in full_text)
            logger.info(f"[LLM:{repo_name}] Haiku stream complete in {elapsed:.2f}s ({total_chars} chars)")
            return

        except anthropic.BadRequestError as e:
            logger.error(f"[LLM:{repo_name}] Haiku bad request: {e}")
            raise HTTPException(502, f"AI service error: {str(e)[:200]}")
        except anthropic.AuthenticationError:
            logger.error(f"[LLM:{repo_name}] Anthropic auth error")
            raise HTTPException(502, "Invalid Anthropic API key.")
        except anthropic.RateLimitError:
            raise HTTPException(429, "AI service rate limited. Please try again in a few minutes.")
        except Exception as haiku_err:
            logger.warning(f"[LLM:{repo_name}] Haiku failed ({haiku_err}), falling back to Sonnet-4")
            full_text = []

        # Fallback: Sonnet-4 streaming
        try:
            logger.info(f"[LLM:{repo_name}] Streaming via claude-sonnet-4")
            async with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=12000,
                system=system_msg,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text_chunk in stream.text_stream:
                    full_text.append(text_chunk)
                    yield text_chunk

            elapsed = time.time() - start
            total_chars = sum(len(c) for c in full_text)
            logger.info(f"[LLM:{repo_name}] Sonnet-4 stream complete in {elapsed:.2f}s ({total_chars} chars)")
            return

        except anthropic.BadRequestError as e:
            logger.error(f"[LLM:{repo_name}] Sonnet bad request: {e}")
            raise HTTPException(502, f"AI service error: {str(e)[:200]}")
        except anthropic.RateLimitError:
            raise HTTPException(429, "AI service rate limited. Please try again in a few minutes.")
        except Exception as e:
            logger.error(f"[LLM:{repo_name}] All Anthropic models failed: {e}")
            raise

    # Fallback: Emergent LLM key (no streaming support — batch only)
    emergent_key = os.environ.get('EMERGENT_LLM_KEY')
    if emergent_key:
        logger.info(f"[LLM:{repo_name}] Using Emergent LLM fallback (batch — no streaming)")
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=emergent_key,
                session_id=f"report-{uuid.uuid4()}",
                system_message=system_msg,
            ).with_model("anthropic", "claude-sonnet-4-6")
            response = await chat.send_message(UserMessage(text=prompt))
            # Emit as a single chunk (no streaming available)
            yield response
            return
        except Exception as e:
            error_str = str(e).lower()
            if "budget" in error_str and "exceeded" in error_str:
                raise HTTPException(503, "AI service budget exceeded.")
            logger.error(f"[LLM:{repo_name}] Emergent LLM error: {e}")
            raise HTTPException(502, f"AI service error: {str(e)[:200]}")

    raise HTTPException(500, "No LLM API key configured. Set ANTHROPIC_API_KEY or EMERGENT_LLM_KEY in .env")


async def record_credit_transaction(user_id: str, amount: int, tx_type: str, reference_id: str, description: str, timestamp: str = None):
    """Record credit transactions consistently."""
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
    await db.credit_transactions.insert_one({
        "id": str(uuid.uuid4()),  # FIX BUG-1: was uuid.uuid4() with missing import
        "user_id": user_id,
        "amount": amount,
        "type": tx_type,
        "reference_id": reference_id,
        "description": description,
        "created_at": timestamp,
    })


# ===== Auth Routes =====
@api_router.post("/auth/verify")
async def verify_auth(request: Request):
    body = await request.json()
    token = body.get("token")
    if not token:
        raise HTTPException(400, "Token required")
    try:
        decoded = await anyio.to_thread.run_sync(_verify_firebase_token_sync, token)
    except Exception as e:
        raise HTTPException(401, f"Invalid token: {str(e)}")

    uid = decoded["uid"]
    email = decoded.get("email", "")
    name = decoded.get("name", email.split("@")[0] if email else "User")
    now = datetime.now(timezone.utc).isoformat()

    result = await db.users.find_one_and_update(
        {"uid": uid},
        {"$setOnInsert": {"uid": uid, "email": email, "display_name": name, "credits": 3, "created_at": now, "updated_at": now}},
        upsert=True,
        return_document=True,
        projection={"_id": 0},
    )
    return result


@api_router.get("/user/profile")
async def get_profile(user=Depends(get_current_user)):
    profile = await db.users.find_one({"uid": user["uid"]}, {"_id": 0})
    if not profile:
        raise HTTPException(404, "User not found")
    return profile


@api_router.get("/user/reports")
async def get_user_reports(user=Depends(get_current_user)):
    reports = await db.reports.find(
        {"generated_by": user["uid"]}, {"_id": 0, "content": 0}
    ).sort("generated_at", -1).to_list(100)
    return {"reports": reports}


# ===== Report Routes =====
@api_router.post("/reports/check")
async def check_report(req: GenerateRequest):
    try:
        owner, repo = parse_repo_url(req.repo_url)
    except ValueError:
        raise HTTPException(400, "Invalid GitHub URL. Use format: https://github.com/owner/repo")

    repo_full_name = f"{owner}/{repo}"
    existing = await db.reports.find_one({"repo_full_name": repo_full_name}, {"_id": 0})

    if not existing:
        return {"exists": False}

    freshness = await check_repo_freshness(existing, owner, repo)
    return {
        "exists": True,
        "report": existing,
        "can_upgrade": freshness["can_upgrade"],
        "upgrade_reason": freshness["reason"],
        "days_old": freshness.get("days_old", 0),
        "new_commits_count": freshness.get("new_commits_count", 0)
    }


@api_router.post("/reports/generate")
async def generate_report(req: GenerateRequest, user=Depends(get_current_user)):
    try:
        owner, repo = parse_repo_url(req.repo_url)
    except ValueError:
        raise HTTPException(400, "Invalid GitHub URL")

    repo_full_name = f"{owner}/{repo}"
    log_prefix = f"[gen:{user['uid'][:8]}:{repo_full_name}]"

    existing = await db.reports.find_one({"repo_full_name": repo_full_name}, {"_id": 0})
    is_upgrade = False

    if existing:
        freshness = await check_repo_freshness(existing, owner, repo)
        if not freshness["can_upgrade"]:
            return {
                "exists": True,
                "report": existing,
                "can_upgrade": False,
                "message": f"A report for this repo already exists. {freshness['reason']}"
            }
        is_upgrade = True
        logger.info(f"{log_prefix} Upgrading existing report (v{existing.get('version', 1)} → v{existing.get('version', 1)+1})")

    now = datetime.now(timezone.utc).isoformat()
    user_doc = await db.users.find_one_and_update(
        {"uid": user["uid"]},
        {"$setOnInsert": {
            "uid": user["uid"], "email": user.get("email", ""),
            "display_name": user.get("name", user.get("email", "User").split("@")[0]),
            "credits": 3, "created_at": now, "updated_at": now,
        }},
        upsert=True,
        return_document=True,
        projection={"_id": 0},
    )

    if user_doc.get("credits", 0) < 2:
        raise HTTPException(402, "Insufficient credits. You need 2 credits to generate a report.")

    uid = user["uid"]
    user_name = user_doc.get("display_name", "Unknown User")

    async def stream_report():
        credits_deducted = False
        start_time = time.time()
        full_content_parts = []

        logger.info(f"{log_prefix} Stream starting")

        try:
            await db.users.update_one(
                {"uid": uid},
                {"$inc": {"credits": -2}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            credits_deducted = True
            logger.info(f"{log_prefix} 2 credits deducted")

            yield f"data: {json.dumps({'type': 'status', 'message': 'Fetching repository data from GitHub...'})}\n\n"

            gh_start = time.time()
            github_data = await fetch_github_data(owner, repo)
            logger.info(f"{log_prefix} GitHub data ready in {time.time()-gh_start:.2f}s")

            yield f"data: {json.dumps({'type': 'status', 'message': 'Generating report with AI (streaming)...'})}\n\n"

            # FIX BUG-2: Stream tokens directly — no more keepalive pings needed.
            # The SSE connection stays alive because tokens arrive continuously.
            llm_start = time.time()
            async for text_chunk in stream_llm_report(github_data):
                full_content_parts.append(text_chunk)
                yield f"data: {json.dumps({'type': 'content', 'text': text_chunk})}\n\n"

            content = "".join(full_content_parts)
            llm_elapsed = time.time() - llm_start
            logger.info(f"{log_prefix} LLM streaming done in {llm_elapsed:.2f}s ({len(content)} chars)")

            # Save report
            report_id = existing["id"] if is_upgrade else str(uuid.uuid4())
            save_now = datetime.now(timezone.utc).isoformat()
            latest_commit_sha = github_data["recent_commits"][0].get("sha", "") if github_data.get("recent_commits") else ""
            latest_commit_date = github_data["recent_commits"][0].get("date", save_now) if github_data.get("recent_commits") else save_now

            report = {
                "id": report_id,
                "repo_full_name": repo_full_name,
                "repo_url": f"https://github.com/{repo_full_name}",
                "title": github_data["repo_info"]["name"],
                "description": github_data["repo_info"]["description"] or "",
                "content": content,
                "language": github_data["repo_info"]["language"] or "",
                "stars": github_data["repo_info"]["stargazers_count"],
                "forks": github_data["repo_info"]["forks_count"],
                "topics": github_data["repo_info"]["topics"],
                "current_owner_id": uid,
                "current_owner_name": user_name,
                "generated_by": uid,
                "generated_at": save_now,
                "updated_at": save_now,
                "version": (existing.get("version", 0) + 1) if is_upgrade else 1,
                "repo_last_commit_sha": latest_commit_sha,
                "repo_last_commit_date": latest_commit_date,
            }

            if is_upgrade:
                previous_owner = {
                    "user_id": existing.get("current_owner_id"),
                    "user_name": existing.get("current_owner_name"),
                    "generated_at": existing.get("generated_at"),
                    "version": existing.get("version", 1),
                    "commit_sha": existing.get("repo_last_commit_sha")
                }
                previous_owners = existing.get("previous_owners", [])
                previous_owners.append(previous_owner)
                report["previous_owners"] = previous_owners
                await db.reports.update_one({"id": report_id}, {"$set": report})
                logger.info(f"{log_prefix} Report upgraded to v{report['version']}")
            else:
                report["previous_owners"] = []
                await db.reports.insert_one(report)
                logger.info(f"{log_prefix} New report v1 created (id={report_id})")

            report.pop("_id", None)

            tx_type = "upgrade" if is_upgrade else "generation"
            tx_desc = f"Upgraded report for {repo_full_name} (v{report['version']})" if is_upgrade else f"Generated report for {repo_full_name}"
            await record_credit_transaction(uid, -2, tx_type, report_id, tx_desc, save_now)

            credits_deducted = False  # success — keep deduction

            updated_user = await db.users.find_one({"uid": uid}, {"_id": 0})
            total_elapsed = time.time() - start_time
            logger.info(f"{log_prefix} SUCCESS in {total_elapsed:.2f}s — {updated_user.get('credits', 0)} credits remaining")
            yield f"data: {json.dumps({'type': 'done', 'report_id': report_id, 'credits_remaining': updated_user.get('credits', 0)})}\n\n"

        except asyncio.CancelledError:
            elapsed = time.time() - start_time
            logger.warning(f"{log_prefix} CANCELLED — client disconnected after {elapsed:.2f}s")
            # finally handles refund
        except HTTPException as e:
            elapsed = time.time() - start_time
            logger.error(f"{log_prefix} HTTP error after {elapsed:.2f}s: {e.detail}")
            try:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e.detail)})}\n\n"
            except Exception:
                pass
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"{log_prefix} UNEXPECTED error after {elapsed:.2f}s: {type(e).__name__}: {e}", exc_info=True)
            try:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Report generation failed. Credits have been refunded.'})}\n\n"
            except Exception:
                pass
        finally:
            if credits_deducted:
                logger.info(f"{log_prefix} REFUND — refunding 2 credits (generation did not complete)")
                await db.users.update_one({"uid": uid}, {"$inc": {"credits": 2}})

    return StreamingResponse(
        stream_report(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@api_router.post("/reports/{report_id}/regenerate")
async def regenerate_report(report_id: str, user=Depends(get_current_user)):
    existing = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Report not found")

    user_doc = await db.users.find_one({"uid": user["uid"]}, {"_id": 0})
    if not user_doc or user_doc.get("credits", 0) < 2:
        raise HTTPException(402, "Insufficient credits. You need 2 credits to regenerate.")

    owner, repo = existing["repo_full_name"].split("/")
    uid = user["uid"]
    log_prefix = f"[regen:{uid[:8]}:{existing['repo_full_name']}]"

    async def stream_regen():
        credits_deducted = False
        full_content_parts = []
        start_time = time.time()

        try:
            await db.users.update_one(
                {"uid": uid},
                {"$inc": {"credits": -2}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            credits_deducted = True
            logger.info(f"{log_prefix} 2 credits deducted for regeneration")

            yield f"data: {json.dumps({'type': 'status', 'message': 'Re-fetching repository data...'})}\n\n"
            await db.github_cache.delete_one({"repo_full_name": existing["repo_full_name"]})
            github_data = await fetch_github_data(owner, repo)

            yield f"data: {json.dumps({'type': 'status', 'message': 'Regenerating report with AI (streaming)...'})}\n\n"

            llm_start = time.time()
            async for text_chunk in stream_llm_report(github_data):
                full_content_parts.append(text_chunk)
                yield f"data: {json.dumps({'type': 'content', 'text': text_chunk})}\n\n"

            content = "".join(full_content_parts)
            logger.info(f"{log_prefix} Regen stream done in {time.time()-llm_start:.2f}s ({len(content)} chars)")

            now = datetime.now(timezone.utc).isoformat()
            await db.reports.update_one({"id": report_id}, {"$set": {
                "content": content,
                "stars": github_data["repo_info"]["stargazers_count"],
                "forks": github_data["repo_info"]["forks_count"],
                "language": github_data["repo_info"]["language"] or "",
                "topics": github_data["repo_info"]["topics"],
                "updated_at": now,
                "version": existing.get("version", 1) + 1,
            }})

            await record_credit_transaction(uid, -2, "regeneration", report_id,
                                            f"Regenerated report for {existing['repo_full_name']}", now)

            credits_deducted = False

            updated_user = await db.users.find_one({"uid": uid}, {"_id": 0})
            total_elapsed = time.time() - start_time
            logger.info(f"{log_prefix} SUCCESS in {total_elapsed:.2f}s")
            yield f"data: {json.dumps({'type': 'done', 'report_id': report_id, 'credits_remaining': updated_user.get('credits', 0)})}\n\n"

        except asyncio.CancelledError:
            logger.warning(f"{log_prefix} CANCELLED after {time.time()-start_time:.2f}s")
        except HTTPException as e:
            logger.error(f"{log_prefix} HTTP error: {e.detail}")
            try:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e.detail)})}\n\n"
            except Exception:
                pass
        except Exception as e:
            logger.error(f"{log_prefix} UNEXPECTED error: {type(e).__name__}: {e}", exc_info=True)
            try:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Regeneration failed. Credits refunded.'})}\n\n"
            except Exception:
                pass
        finally:
            if credits_deducted:
                logger.info(f"{log_prefix} REFUND — refunding 2 credits")
                await db.users.update_one({"uid": uid}, {"$inc": {"credits": 2}})

    return StreamingResponse(
        stream_regen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@api_router.get("/reports")
async def list_reports(search: str = "", page: int = 1, limit: int = 20):
    query = {}
    if search:
        query = {"$or": [
            {"repo_full_name": {"$regex": search, "$options": "i"}},
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
            {"language": {"$regex": search, "$options": "i"}},
        ]}
    skip = (page - 1) * limit
    total = await db.reports.count_documents(query)
    reports = await db.reports.find(query, {"_id": 0, "content": 0}).sort("generated_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"reports": reports, "total": total, "page": page, "limit": limit}


@api_router.get("/reports/{report_id}")
async def get_report(report_id: str):
    report = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not report:
        raise HTTPException(404, "Report not found")
    return report


@api_router.get("/reports/{report_id}/history")
async def get_report_history(report_id: str):
    report = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not report:
        raise HTTPException(404, "Report not found")

    history = []
    for prev_owner in report.get("previous_owners", []):
        history.append({
            "version": prev_owner.get("version", 0),
            "owner_name": prev_owner.get("user_name", "Unknown"),
            "owner_id": prev_owner.get("user_id"),
            "generated_at": prev_owner.get("generated_at"),
            "commit_sha": prev_owner.get("commit_sha", "")[:7]
        })
    history.append({
        "version": report.get("version", 1),
        "owner_name": report.get("current_owner_name", "Unknown"),
        "owner_id": report.get("current_owner_id"),
        "generated_at": report.get("generated_at"),
        "commit_sha": report.get("repo_last_commit_sha", "")[:7],
        "is_current": True
    })
    return {
        "report_id": report_id,
        "repo_name": report.get("repo_full_name"),
        "current_version": report.get("version", 1),
        "history": sorted(history, key=lambda x: x["version"])
    }


@api_router.put("/reports/{report_id}")
async def edit_report(report_id: str, req: EditRequest, user=Depends(get_current_user)):
    existing = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Report not found")

    user_doc = await db.users.find_one({"uid": user["uid"]}, {"_id": 0})
    if not user_doc or user_doc.get("credits", 0) < 1:
        raise HTTPException(402, "Insufficient credits. You need 1 credit to edit.")

    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"uid": user["uid"]}, {"$inc": {"credits": -1}, "$set": {"updated_at": now}})
    await db.reports.update_one({"id": report_id}, {"$set": {
        "content": req.content, "updated_at": now, "version": existing.get("version", 1) + 1
    }})

    await record_credit_transaction(
        user_id=user["uid"], amount=-1, tx_type="edit", reference_id=report_id,
        description=f"Edited report for {existing['repo_full_name']}", timestamp=now
    )

    updated_user = await db.users.find_one({"uid": user["uid"]}, {"_id": 0})
    return {"message": "Report updated", "credits_remaining": updated_user.get("credits", 0)}


# ===== Credit/Payment Routes =====
@api_router.get("/credits/packages")
async def get_packages():
    return {"packages": CREDIT_PACKAGES}


@api_router.post("/credits/checkout")
async def create_checkout(req: CheckoutRequest, request: Request, user=Depends(get_current_user)):
    package = CREDIT_PACKAGES.get(req.package_id)
    if not package:
        raise HTTPException(400, "Invalid package")

    stripe_key = os.environ.get('STRIPE_API_KEY')
    if not stripe_key:
        raise HTTPException(500, "Payment not configured")

    host_url = str(request.base_url).rstrip('/')
    webhook_url = f"{host_url}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=stripe_key, webhook_url=webhook_url)

    success_url = f"{req.origin_url}/credits/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{req.origin_url}/credits"

    checkout_req = CheckoutSessionRequest(
        amount=package["price"],
        currency="usd",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"user_id": user["uid"], "package_id": req.package_id, "credits": str(package["credits"])}
    )

    session = await stripe_checkout.create_checkout_session(checkout_req)

    now = datetime.now(timezone.utc).isoformat()
    await db.payment_transactions.insert_one({
        "id": str(uuid.uuid4()),
        "session_id": session.session_id,
        "user_id": user["uid"], "amount": package["price"], "currency": "usd",
        "credits": package["credits"], "package_id": req.package_id,
        "status": "pending", "payment_status": "pending",
        "created_at": now, "updated_at": now,
    })

    return {"url": session.url, "session_id": session.session_id}


@api_router.get("/credits/checkout/status/{session_id}")
async def check_checkout_status(session_id: str, request: Request, user=Depends(get_current_user)):
    stripe_key = os.environ.get('STRIPE_API_KEY')
    host_url = str(request.base_url).rstrip('/')
    webhook_url = f"{host_url}/api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=stripe_key, webhook_url=webhook_url)

    status = await stripe_checkout.get_checkout_status(session_id)

    if status.payment_status == "paid":
        tx = await db.payment_transactions.find_one_and_update(
            {"session_id": session_id, "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "complete", "payment_status": "paid", "updated_at": datetime.now(timezone.utc).isoformat()}},
            projection={"_id": 0},
        )
        if tx:
            credits_to_add = tx.get("credits", 0)
            now = datetime.now(timezone.utc).isoformat()
            await db.users.update_one(
                {"uid": user["uid"]},
                {"$inc": {"credits": credits_to_add}, "$set": {"updated_at": now}}
            )
            await record_credit_transaction(
                user_id=user["uid"], amount=credits_to_add, tx_type="purchase",
                reference_id=tx.get("id"),
                description=f"Purchased {credits_to_add} credits ({tx.get('package_id')} package)",
                timestamp=now
            )
            logger.info(f"Credited {credits_to_add} credits to user {user['uid']} for session {session_id}")
    else:
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"status": status.status, "payment_status": status.payment_status, "updated_at": datetime.now(timezone.utc).isoformat()}}
        )

    updated_user = await db.users.find_one({"uid": user["uid"]}, {"_id": 0})
    return {
        "status": status.status, "payment_status": status.payment_status,
        "amount_total": status.amount_total, "currency": status.currency,
        "credits_remaining": updated_user.get("credits", 0) if updated_user else 0,
    }


@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    try:
        body = await request.body()
        stripe_key = os.environ.get('STRIPE_API_KEY')
        host_url = str(request.base_url).rstrip('/')
        webhook_url = f"{host_url}/api/webhook/stripe"
        stripe_checkout = StripeCheckout(api_key=stripe_key, webhook_url=webhook_url)
        webhook_response = await stripe_checkout.handle_webhook(body, request.headers.get("Stripe-Signature"))

        if webhook_response.payment_status == "paid":
            tx = await db.payment_transactions.find_one({"session_id": webhook_response.session_id}, {"_id": 0})
            if tx and tx.get("payment_status") != "paid":
                now = datetime.now(timezone.utc).isoformat()
                await db.users.update_one(
                    {"uid": tx["user_id"]},
                    {"$inc": {"credits": tx.get("credits", 0)}, "$set": {"updated_at": now}}
                )
                await db.payment_transactions.update_one(
                    {"session_id": webhook_response.session_id},
                    {"$set": {"status": "complete", "payment_status": "paid", "updated_at": now}}
                )
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        return {"status": "error"}


@api_router.get("/stats")
async def get_stats():
    total_reports = await db.reports.count_documents({})
    total_users = await db.users.count_documents({})
    return {"total_reports": total_reports, "total_users": total_users}


@api_router.get("/user/transactions")
async def get_user_transactions(user=Depends(get_current_user)):
    payments = await db.payment_transactions.find(
        {"user_id": user["uid"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    credits = await db.credit_transactions.find(
        {"user_id": user["uid"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return {"payments": payments, "credits": credits}


# Include router and middleware
# NOTE: Router will be included at END of file after all routes are defined
# app.include_router(api_router)  # MOVED TO END

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_db_indexes():
    """Ensure database indexes exist for performance and uniqueness."""
    import pymongo
    logger.info("Initializing database indexes...")
    try:
        # Users
        await db.users.create_index("uid", unique=True)

        # Reports — FIX BUG-4: repo_full_name index was commented out
        await db.reports.create_index("id", unique=True)
        # await db.reports.create_index("repo_full_name")           # ← was commented out
        await db.reports.create_index("generated_by")
        await db.reports.create_index([("generated_at", pymongo.DESCENDING)])

        # Transactions
        await db.payment_transactions.create_index("session_id", unique=True)
        await db.payment_transactions.create_index("user_id")
        await db.credit_transactions.create_index("user_id")
        await db.credit_transactions.create_index([("created_at", pymongo.DESCENDING)])

        # GitHub cache
        await db.github_cache.create_index("repo_full_name", unique=True)

        # Enterprise collections — FIX BUG-9: these were missing
        await db.organizations.create_index("id", unique=True)
        await db.organizations.create_index("owner_user_id")
        await db.organizations.create_index("github_org_id")
        await db.analysis_jobs.create_index("id", unique=True)
        await db.analysis_jobs.create_index("organization_id")
        await db.analysis_jobs.create_index([("status", pymongo.ASCENDING), ("organization_id", pymongo.ASCENDING)])
        await db.organization_wikis.create_index("id", unique=True)

        logger.info("Database indexes configured successfully.")
    except Exception as e:
        logger.error(f"Failed to create database indexes: {e}")


@app.on_event("startup")
async def startup_checks():
    """Log configuration status at startup."""
    checks = {
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "EMERGENT_LLM_KEY": bool(os.environ.get("EMERGENT_LLM_KEY")),
        "STRIPE_API_KEY": bool(os.environ.get("STRIPE_API_KEY")),
        "GITHUB_CLIENT_ID": bool(os.environ.get("GITHUB_CLIENT_ID")),
        "CELERY_TASKS": CELERY_AVAILABLE,
        "STRIPE_LIB": STRIPE_AVAILABLE,
    }
    for key, ok in checks.items():
        status = "✓" if ok else "✗ MISSING"
        logger.info(f"[startup] {key}: {status}")

    if not checks["ANTHROPIC_API_KEY"] and not checks["EMERGENT_LLM_KEY"]:
        logger.critical("[startup] NO LLM API KEY configured — report generation will fail!")


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()


# ===== Enterprise / Organization Routes =====

# GitHub OAuth configuration
GITHUB_CLIENT_ID = os.environ.get('GITHUB_CLIENT_ID')
GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_CLIENT_SECRET')
GITHUB_OAUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

# Calculate frontend URL from backend URL
BACKEND_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001')
if '/api' in BACKEND_URL:
    FRONTEND_URL = BACKEND_URL.replace('/api', '')
else:
    FRONTEND_URL = BACKEND_URL.replace(':8001', ':3000')

logger.info(f"[OAUTH] Frontend URL: {FRONTEND_URL}")
logger.info(f"[OAUTH] GitHub callback: {FRONTEND_URL}/enterprise/callback")


@api_router.get("/enterprise/github/authorize")
async def github_authorize():
    """Redirect to GitHub OAuth for organization access"""
    redirect_uri = f"{FRONTEND_URL}/enterprise/callback"
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:org,repo,user:email",
        "state": secrets.token_urlsafe(16)
    }
    return {"url": f"{GITHUB_OAUTH_URL}?{urlencode(params)}"}


@api_router.post("/enterprise/github/callback")
async def github_callback(request: GithubCallbackRequest, user=Depends(get_current_user)):
    """
    Handle GitHub OAuth callback - exchange code for access token and fetch organizations
    """
    code = request.code
    user_uid = user.get("uid", "unknown")
    logger.info(f"[GITHUB-CALLBACK] Starting for user {user_uid[:8]}...")
    
    try:
        async with httpx.AsyncClient() as client:
            # Exchange authorization code for access token
            logger.info(f"[GITHUB-CALLBACK] Exchanging code for access token...")
            token_resp = await client.post(
                GITHUB_TOKEN_URL,
                data={"client_id": GITHUB_CLIENT_ID, "client_secret": GITHUB_CLIENT_SECRET, "code": code},
                headers={"Accept": "application/json"}
            )
            
            if token_resp.status_code != 200:
                logger.error(f"[GITHUB-CALLBACK] Token exchange failed: {token_resp.status_code} - {token_resp.text}")
                raise HTTPException(400, "Failed to exchange code for token")
            
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            
            if not access_token:
                logger.error(f"[GITHUB-CALLBACK] No access token in response: {token_data}")
                raise HTTPException(400, "No access token received from GitHub")

            # Fetch user's organizations
            logger.info(f"[GITHUB-CALLBACK] Fetching organizations...")
            orgs_resp = await client.get(
                "https://api.github.com/user/orgs",
                headers={
                    "Authorization": f"Bearer {access_token}", 
                    "Accept": "application/vnd.github.v3+json", 
                    "User-Agent": "Gitopedia/1.0"
                }
            )
            
            if orgs_resp.status_code != 200:
                logger.error(f"[GITHUB-CALLBACK] Failed to fetch orgs: {orgs_resp.status_code} - {orgs_resp.text}")
                raise HTTPException(400, "Failed to fetch organizations from GitHub")

            organizations = orgs_resp.json()
            logger.info(f"[GITHUB-CALLBACK] Found {len(organizations)} organization(s)")
            
            # Handle case when user has no organizations
            if not organizations or len(organizations) == 0:
                logger.warning(f"[GITHUB-CALLBACK] User {user_uid[:8]} has no GitHub organizations")
                return {
                    "access_token": access_token,
                    "organizations": [],
                    "message": "No organizations found. You need to be a member of at least one GitHub organization to use Gitopedia Enterprise."
                }
            
            # Store the GitHub access token for the user
            await db.users.update_one(
                {"uid": user_uid},
                {"$set": {"github_access_token": access_token, "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            logger.info(f"[GITHUB-CALLBACK] Stored access token for user {user_uid[:8]}")
            
            # Format organizations response
            formatted_orgs = [
                {
                    "id": org["id"], 
                    "login": org["login"], 
                    "name": org.get("description") or org["login"],
                    "avatar_url": org.get("avatar_url"), 
                    "url": org.get("html_url")
                }
                for org in organizations
            ]
            
            logger.info(f"[GITHUB-CALLBACK] SUCCESS - returning {len(formatted_orgs)} organizations")
            return {
                "access_token": access_token,
                "organizations": formatted_orgs
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GITHUB-CALLBACK] Unexpected error for user {user_uid[:8]}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to complete GitHub authorization: {str(e)}")


class ConnectOrganizationRequest(BaseModel):
    github_org_id: int
    github_org_login: str
    github_org_name: str
    github_token: str
    avatar_url: Optional[str] = None

@api_router.post("/enterprise/organizations/connect")
async def connect_organization(
    request: ConnectOrganizationRequest,
    user=Depends(get_current_user)
):
    """
    Connect a GitHub organization to the user's account
    """
    user_uid = user.get("uid", "unknown")
    logger.info(f"[ORG-CONNECT] User {user_uid[:8]} connecting org: {request.github_org_login}")
    
    try:
        existing = await db.organizations.find_one(
            {"github_org_id": request.github_org_id, "owner_user_id": user_uid}, {"_id": 0}
        )
        if existing:
            logger.info(f"[ORG-CONNECT] Organization already exists: {request.github_org_login}")
            return {"message": "Organization already connected", "organization": existing}

        # Fetch organization details from GitHub
        logger.info(f"[ORG-CONNECT] Fetching org details from GitHub API...")
        async with httpx.AsyncClient() as client:
            org_resp = await client.get(
                f"https://api.github.com/orgs/{request.github_org_login}",
                headers={
                    "Authorization": f"Bearer {request.github_token}", 
                    "Accept": "application/vnd.github.v3+json", 
                    "User-Agent": "Gitopedia/1.0"
                }
            )
            if org_resp.status_code != 200:
                logger.error(f"[ORG-CONNECT] GitHub API error: {org_resp.status_code} - {org_resp.text}")
                raise HTTPException(403, "Cannot access this organization. Please check permissions.")
            org_data = org_resp.json()
            total_repos = org_data.get("public_repos", 0)

        logger.info(f"[ORG-CONNECT] Organization has {total_repos} public repos")

        if total_repos <= 50:
            pricing_tier, price = "small", 50
        elif total_repos <= 100:
            pricing_tier, price = "medium", 100
        else:
            pricing_tier, price = "large", 200

        org_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        organization = {
            "id": org_id,
            "github_org_id": request.github_org_id,
            "github_org_login": request.github_org_login,
            "github_org_name": request.github_org_name or request.github_org_login,
            "avatar_url": request.avatar_url or org_data.get("avatar_url"),
            "owner_user_id": user_uid,
            "access_token": request.github_token,  # TODO: encrypt before storing (BUG-5)
            "total_repos": total_repos,
            "analyzed_repos": 0,
            "last_analyzed_at": None,
            "wiki_id": None,
            "wiki_access_token": None,
            "wiki_url": None,
            "pricing_tier": pricing_tier,
            "payment_status": "pending",
            "stripe_session_id": None,
            "paid_amount": price,
            "created_at": now,
            "updated_at": now
        }

        logger.info(f"[ORG-CONNECT] Inserting organization {org_id} into database...")
        result = await db.organizations.insert_one(organization)
        logger.info(f"[ORG-CONNECT] Organization inserted with MongoDB ID: {result.inserted_id}")
        
        organization.pop("_id", None)

        logger.info(f"[ORG-CONNECT] SUCCESS - Organization {request.github_org_login} connected")
        return {
            "message": "Organization connected successfully",
            "organization": organization,
            "pricing": {"tier": pricing_tier, "amount": price, "total_repos": total_repos}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ORG-CONNECT] Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to connect organization: {str(e)}")


@api_router.get("/enterprise/organizations")
async def list_organizations(user=Depends(get_current_user)):
    orgs = await db.organizations.find(
        {"owner_user_id": user["uid"]}, {"_id": 0, "access_token": 0}
    ).to_list(100)
    return {"organizations": orgs}


@api_router.get("/enterprise/organizations/{org_id}")
async def get_organization(org_id: str, user=Depends(get_current_user)):
    org = await db.organizations.find_one(
        {"id": org_id, "owner_user_id": user["uid"]}, {"_id": 0, "access_token": 0}
    )
    if not org:
        raise HTTPException(404, "Organization not found")

    active_job = await db.analysis_jobs.find_one(
        {"organization_id": org_id, "status": {"$in": ["queued", "processing"]}}, {"_id": 0}
    )
    return {"organization": org, "active_job": active_job}


@api_router.post("/enterprise/organizations/{org_id}/analyze")
async def start_organization_analysis(org_id: str, user=Depends(get_current_user)):
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Payment processing is not available.")
    if not CELERY_AVAILABLE:
        raise HTTPException(503, "Background analysis tasks are not available.")

    try:
        org = await db.organizations.find_one(
            {"id": org_id, "owner_user_id": user["uid"]}, {"_id": 0}
        )
        if not org:
            raise HTTPException(404, "Organization not found")

        if org.get("payment_status") != "paid":
            # FIX BUG-7: use top-level stripe_lib; run sync Stripe call in executor
            stripe_lib.api_key = os.environ.get('STRIPE_API_KEY')
            session = await anyio.to_thread.run_sync(
                lambda: stripe_lib.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'usd',
                            'product_data': {
                                'name': f'Organization Analysis - {org["github_org_name"]}',
                                'description': f'{org["total_repos"]} repositories ({org["pricing_tier"]} tier)',
                            },
                            'unit_amount': org["paid_amount"] * 100,
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url=f"{FRONTEND_URL}/enterprise/organizations/{org_id}?payment=success",
                    cancel_url=f"{FRONTEND_URL}/enterprise/organizations/{org_id}?payment=cancelled",
                    metadata={'organization_id': org_id, 'user_id': user["uid"], 'type': 'organization_analysis'}
                )
            )

            await db.organizations.update_one({"id": org_id}, {"$set": {"stripe_session_id": session.id}})
            return {"requires_payment": True, "checkout_url": session.url, "session_id": session.id, "amount": org["paid_amount"]}

        active_job = await db.analysis_jobs.find_one(
            {"organization_id": org_id, "status": {"$in": ["queued", "processing"]}}, {"_id": 0}
        )
        if active_job:
            return {"message": "Analysis already in progress", "job": active_job}

        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        job = {
            "id": job_id, "organization_id": org_id, "user_id": user["uid"],
            "job_type": "full_analysis", "status": "queued",
            "total_repos": 0, "processed_repos": 0, "failed_repos": 0,
            "progress_percentage": 0, "started_at": None, "completed_at": None,
            "estimated_completion": None, "generated_reports": [], "failed_repo_names": [],
            "wiki_id": None, "error_message": None, "retry_count": 0,
            "created_at": now, "updated_at": now
        }
        await db.analysis_jobs.insert_one(job)

        # FIX BUG-8: use module-level import, check CELERY_AVAILABLE above
        task = celery_analyze_organization.delay(job_id, org_id, org["access_token"])
        logger.info(f"[enterprise] Analysis job {job_id} started for org {org_id}, Celery task: {task.id}")

        return {"message": "Analysis started", "job_id": job_id, "celery_task_id": task.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Start analysis error: {e}")
        raise HTTPException(500, f"Failed to start analysis: {str(e)}")


@api_router.get("/enterprise/jobs/{job_id}")
async def get_job_status(job_id: str, user=Depends(get_current_user)):
    job = await db.analysis_jobs.find_one({"id": job_id, "user_id": user["uid"]}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    return {"job": job}


@api_router.post("/enterprise/payment/webhook")
async def enterprise_payment_webhook(request: Request):
    if not STRIPE_AVAILABLE:
        raise HTTPException(503, "Stripe not available")
    stripe_lib.api_key = os.environ.get('STRIPE_API_KEY')

    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe_lib.Webhook.construct_event(payload, sig_header, os.environ.get('STRIPE_WEBHOOK_SECRET', 'test'))
    except Exception:
        event = json.loads(payload)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = session.get('metadata', {})
        if metadata.get('type') == 'organization_analysis':
            org_id = metadata.get('organization_id')
            await db.organizations.update_one(
                {"id": org_id},
                {"$set": {"payment_status": "paid", "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            logger.info(f"[enterprise] Payment completed for organization {org_id}")

    return {"status": "success"}


# ===== Wiki Routes =====
@api_router.get("/wiki/{org_login}/{access_token}")
async def get_wiki_public(org_login: str, access_token: str):
    org = await db.organizations.find_one(
        {"github_org_login": org_login, "wiki_access_token": access_token}, {"_id": 0}
    )
    if not org:
        raise HTTPException(404, "Wiki not found or invalid access token")
    if not org.get("wiki_id"):
        raise HTTPException(404, "Wiki has not been generated yet")

    wiki = await db.organization_wikis.find_one({"id": org["wiki_id"]}, {"_id": 0})
    if not wiki:
        raise HTTPException(404, "Wiki content not found")

    return {
        "organization": {
            "name": org["github_org_name"],
            "login": org["github_org_login"],
            "avatar_url": org.get("avatar_url"),
            "total_repos": org["total_repos"],
            "analyzed_repos": org["analyzed_repos"]
        },
        "wiki": wiki
    }


# ===== Include API Router =====
# This MUST be at the end, after all routes are defined
app.include_router(api_router)
