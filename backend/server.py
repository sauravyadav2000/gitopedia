from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
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
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
import uuid
from datetime import datetime, timezone
import time
import anthropic

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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


# ===== Helper Functions =====
async def check_repo_freshness(report: dict, owner: str, repo: str) -> dict:
    """Check if report needs upgrade based on age and new commits."""
    try:
        # Calculate days since last update
        report_date = datetime.fromisoformat(report["generated_at"])
        days_old = (datetime.now(timezone.utc) - report_date).days
        
        # Check if report is >30 days old
        if days_old < 30:
            return {
                "can_upgrade": False,
                "reason": f"Report is still fresh (updated {days_old} days ago)",
                "days_old": days_old
            }
        
        # Fetch latest commit from GitHub
        async with httpx.AsyncClient(timeout=10) as client:
            headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "Gitopedia/1.0"}
            commits_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1",
                headers=headers
            )
            
            if commits_resp.status_code != 200:
                return {
                    "can_upgrade": False,
                    "reason": "Could not fetch latest commits from GitHub"
                }
            
            commits = commits_resp.json()
            if not commits:
                return {
                    "can_upgrade": False,
                    "reason": "No commits found"
                }
            
            latest_commit = commits[0]
            latest_commit_sha = latest_commit["sha"]
            latest_commit_date = latest_commit["commit"]["author"]["date"]
            
            # Check if there are new commits since report generation
            report_commit_sha = report.get("repo_last_commit_sha")
            if latest_commit_sha == report_commit_sha:
                return {
                    "can_upgrade": False,
                    "reason": "No new commits since last report",
                    "days_old": days_old
                }
            
            # Count commits between report and now
            compare_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/compare/{report_commit_sha}...{latest_commit_sha}",
                headers=headers
            )
            
            new_commits_count = 0
            if compare_resp.status_code == 200:
                compare_data = compare_resp.json()
                new_commits_count = compare_data.get("total_commits", 0)
            
            return {
                "can_upgrade": True,
                "reason": f"Report is {days_old} days old with {new_commits_count} new commits",
                "days_old": days_old,
                "new_commits_count": new_commits_count,
                "latest_commit_date": latest_commit_date,
                "latest_commit_sha": latest_commit_sha
            }
            
    except Exception as e:
        logger.error(f"Error checking repo freshness: {e}")
        return {
            "can_upgrade": False,
            "reason": "Error checking repository status"
        }


# ===== Auth Dependencies =====
async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not creds:
        raise HTTPException(401, "Authentication required")
    try:
        decoded = firebase_auth.verify_id_token(creds.credentials)
        return decoded
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(401, "Invalid authentication token")

async def get_optional_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not creds:
        return None
    try:
        return firebase_auth.verify_id_token(creds.credentials)
    except:
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
    """Fetch GitHub data with optional fast mode for quicker LLM generation."""
    cache_key = f"{owner}/{repo}"
    cached = await db.github_cache.find_one({"repo_full_name": cache_key}, {"_id": 0})
    if cached:
        try:
            cached_time = datetime.fromisoformat(cached["fetched_at"])
            if (datetime.now(timezone.utc) - cached_time).total_seconds() < GITHUB_CACHE_TTL:
                return cached["data"]
        except:
            pass

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
            raise HTTPException(400, "Private repositories are not supported yet. Only public repos are available in this version.")

        default_branch = repo_info.get("default_branch", "main")

        # Parallel fetches
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
                logger.warning(f"[{owner}/{repo}] Unable to decode README: {e}")
                readme_content = "Unable to decode README"
        elif isinstance(readme_resp, Exception):
            logger.warning(f"[{owner}/{repo}] Failed to fetch README: {readme_resp}")

        file_tree = []
        if not isinstance(tree_resp, Exception) and tree_resp.status_code == 200:
            tree_data = tree_resp.json()
            # Directories and patterns to exclude for optimization
            exclude_patterns = [
                'node_modules/', '.git/', 'dist/', 'build/', 'target/', 'vendor/',
                '.next/', '.nuxt/', 'out/', 'coverage/', '.cache/', '__pycache__/',
                'venv/', 'env/', '.venv/', 'site-packages/', 'pkg/', 'bin/',
                '.DS_Store', 'thumbs.db', '.idea/', '.vscode/', '.terraform/',
                'bower_components/', 'jspm_packages/', '.gradle/', '.mvn/', 'test/',
                'tests/', 'spec/', '__tests__/', '.pytest_cache/', 'public/static/'
            ]
            # Binary file extensions to exclude
            binary_extensions = [
                '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico', '.svg', '.webp',
                '.mp4', '.avi', '.mov', '.wmv', '.flv', '.pdf', '.zip', '.tar',
                '.gz', '.rar', '.7z', '.exe', '.dll', '.so', '.dylib', '.jar',
                '.war', '.ear', '.woff', '.woff2', '.ttf', '.eot', '.otf', '.map'
            ]
            
            # Limit file tree size based on mode
            max_files = 300 if fast_mode else 1000
            
            for item in (tree_data.get("tree") or [])[:max_files]:
                path = item.get("path", "")
                
                # Skip if matches exclude patterns
                if any(pattern in path for pattern in exclude_patterns):
                    continue
                
                # Skip binary files
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

        # Fetch key config files
        config_files = {}
        key_files = ["package.json", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml",
                      "Dockerfile", "docker-compose.yml", "Makefile", "tsconfig.json", "pyproject.toml"]
        
        # Sequentially fetch config files (fine for <10 small files)
        for filepath in key_files:
            try:
                resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{filepath}", headers=headers
                )
                if resp.status_code == 200:
                    content_data = resp.json()
                    if content_data.get("size", 0) <= 100000:
                        try:
                            content = base64.b64decode(content_data.get("content", "")).decode("utf-8", errors="replace")
                            config_files[filepath] = content[:5000]
                        except Exception as e:
                            logger.warning(f"[{owner}/{repo}] Error decoding config file {filepath}: {e}")
            except Exception as e:
                logger.warning(f"[{owner}/{repo}] Network error fetching {filepath}: {e}")

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
    
    # Limit file tree to 150 for speed
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

    # Detect if repo has database models/migrations
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


async def generate_report_content(data: dict, use_fast_model: bool = True) -> str:
    """Generate report content using LLM with speed optimization."""
    repo_name = data["repo_info"].get("full_name", "unknown")
    
    prompt = build_report_prompt(data)
    prompt_tokens = len(prompt) // 4  # Rough estimate
    logger.info(f"[LLM] Prompt prepared for {repo_name} (~{prompt_tokens} tokens)")
    
    system_msg = "You are a senior software architect. Analyze this repository and create a concise, technical report with key insights, architecture overview, tech stack, and directory structure. Include Mermaid diagrams where helpful. Be direct and actionable."

    # Priority 1: Direct Anthropic API key
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    if anthropic_key:
        try:
            logger.info(f"[LLM] Using direct Anthropic API for {repo_name}")
            client = anthropic.AsyncAnthropic(api_key=anthropic_key, timeout=180.0)
            
            # Use fast model (Haiku) by default for <45s generation
            if use_fast_model:
                try:
                    api_start = time.time()
                    logger.info(f"[LLM] Calling claude-haiku (FAST MODE) for {repo_name}")
                    message = await client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=8000,  # Reduced from 16000 for speed
                        system=system_msg,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    api_duration = time.time() - api_start
                    result = message.content[0].text
                    logger.info(f"[LLM SUCCESS] claude-haiku responded in {api_duration:.2f}s ({len(result)} chars) for {repo_name}")
                    return result
                except Exception as fast_error:
                    logger.warning(f"[LLM FALLBACK] Fast model failed, trying Sonnet for {repo_name}")
                    # Fall through to Sonnet
            
            # Fallback or premium mode: Use Sonnet 4
            try:
                api_start = time.time()
                logger.info(f"[LLM] Calling claude-sonnet-4 for {repo_name}")
                message = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=12000,  # Reduced from 16000
                    system=system_msg,
                    messages=[{"role": "user", "content": prompt}],
                )
                api_duration = time.time() - api_start
                result = message.content[0].text
                logger.info(f"[LLM SUCCESS] claude-sonnet-4 responded in {api_duration:.2f}s ({len(result)} chars) for {repo_name}")
                return result
            except Exception as sonnet_error:
                logger.error(f"[LLM ERROR] All models failed for {repo_name}: {sonnet_error}")
                raise
                
        except anthropic.BadRequestError as e:
            logger.error(f"Anthropic bad request: {e}")
            raise HTTPException(502, f"AI service error: {str(e)[:200]}")
        except anthropic.AuthenticationError as e:
            logger.error(f"Anthropic auth error: {e}")
            raise HTTPException(502, "Invalid Anthropic API key.")
        except anthropic.RateLimitError:
            raise HTTPException(429, "AI service rate limited. Please try again in a few minutes.")
        except Exception as e:
            logger.error(f"Anthropic error, will try Emergent fallback: {e}")

    # Priority 2: Emergent LLM key fallback
    emergent_key = os.environ.get('EMERGENT_LLM_KEY')
    if emergent_key:
        try:
            logger.info("Using Emergent LLM key for generation")
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=emergent_key,
                session_id=f"report-{uuid.uuid4()}",
                system_message=system_msg,
            ).with_model("anthropic", "claude-sonnet-4-6")
            response = await chat.send_message(UserMessage(text=prompt))
            return response
        except Exception as e:
            error_str = str(e).lower()
            if "budget" in error_str and "exceeded" in error_str:
                raise HTTPException(503, "AI service budget exceeded. Add balance at Profile > Universal Key > Add Balance.")
            logger.error(f"Emergent LLM error: {e}")
            raise HTTPException(502, f"AI service error: {str(e)[:200]}")

    raise HTTPException(500, "No LLM API key configured. Set ANTHROPIC_API_KEY or EMERGENT_LLM_KEY in .env")


async def record_credit_transaction(user_id: str, amount: int, tx_type: str, reference_id: str, description: str, timestamp: str = None):
    """Helper to record credit transactions consistently."""
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()
        
    await db.credit_transactions.insert_one({
        "id": str(uuid.uuid4()), 
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
        decoded = firebase_auth.verify_id_token(token)
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
    
    # Check if report can be upgraded
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

    # Check if report exists and if it's upgradeable
    existing = await db.reports.find_one({"repo_full_name": repo_full_name}, {"_id": 0})
    is_upgrade = False
    
    if existing:
        # Check if can upgrade
        freshness = await check_repo_freshness(existing, owner, repo)
        
        if not freshness["can_upgrade"]:
            return {
                "exists": True,
                "report": existing,
                "can_upgrade": False,
                "message": f"A report for this repo already exists. {freshness['reason']}"
            }
        
        # Can upgrade!
        is_upgrade = True
        logger.info(f"[UPGRADE] User {user['uid']} upgrading report for {repo_full_name}")
    
    # Ensure user exists in DB (race condition safe with upsert)
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
        logger.info(f"[GENERATION START] User: {uid}, Repo: {repo_full_name}")
        
        try:
            # Deduct credits INSIDE the stream so refund is guaranteed by finally
            await db.users.update_one(
                {"uid": uid},
                {"$inc": {"credits": -2}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            credits_deducted = True
            logger.info(f"[CREDITS] Deducted 2 credits from user {uid}")

            yield f"data: {json.dumps({'type': 'status', 'message': 'Fetching repository data from GitHub...'})}\n\n"
            
            gh_start = time.time()
            github_data = await fetch_github_data(owner, repo)
            gh_duration = time.time() - gh_start
            logger.info(f"[GITHUB] Fetched data for {repo_full_name} in {gh_duration:.2f}s")

            yield f"data: {json.dumps({'type': 'status', 'message': 'Analyzing codebase with AI...'})}\n\n"
            
            # Generate content with keepalive pings to prevent ingress timeout
            llm_start = time.time()
            logger.info(f"[LLM START] Starting generation for {repo_full_name} (user: {uid})")
            generation_task = asyncio.create_task(generate_report_content(github_data))
            request_id = str(uuid.uuid4())
            logger.info(f"[{request_id}] LLM task created")
            ping_count = 0
            
            # Keep sending pings until generation completes
            while not generation_task.done():
                try:
                    # Wait up to 15 seconds for completion
                    content = await asyncio.wait_for(asyncio.shield(generation_task), timeout=15.0)
                    logger.info(f"[LLM COMPLETE] Generation completed for {repo_full_name}")
                    break
                except asyncio.TimeoutError:
                    # Task still running - send keepalive ping
                    ping_count += 1
                    elapsed = time.time() - llm_start
                    ping_msg = f"data: {json.dumps({'type': 'ping', 'message': f'Still processing... ({int(elapsed)}s elapsed)'})}\n\n"
                    logger.info(f"[KEEPALIVE] Ping #{ping_count} sent ({elapsed:.1f}s elapsed) for {repo_full_name}")
                    yield ping_msg
            
            # Get result if not already retrieved
            if not generation_task.done():
                content = await generation_task
            else:
                content = generation_task.result()

            llm_duration = time.time() - llm_start
            logger.info(f"[LLM DONE] Generated {len(content)} chars in {llm_duration:.2f}s for {repo_full_name}")
            yield f"data: {json.dumps({'type': 'status', 'message': 'Streaming report...'})}\n\n"

            chunk_size = 40
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
                await asyncio.sleep(0.012)

            # Save or update report with ownership tracking
            report_id = existing["id"] if is_upgrade else str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            
            # Get latest commit info for tracking
            latest_commit_sha = github_data["recent_commits"][0].get("sha", "") if github_data.get("recent_commits") else ""
            latest_commit_date = github_data["recent_commits"][0].get("date", now) if github_data.get("recent_commits") else now
            
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
                
                # Ownership fields
                "current_owner_id": uid,
                "current_owner_name": user_name,
                
                # Versioning fields
                "generated_by": uid,  # Kept for backward compatibility
                "generated_at": now,
                "updated_at": now,
                "version": (existing.get("version", 0) + 1) if is_upgrade else 1,
                
                # Freshness tracking
                "repo_last_commit_sha": latest_commit_sha,
                "repo_last_commit_date": latest_commit_date,
            }
            
            if is_upgrade:
                # Archive previous owner to history
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
                
                # Update existing report
                await db.reports.update_one(
                    {"id": report_id},
                    {"$set": report}
                )
                logger.info(f"[UPGRADE SUCCESS] Report upgraded to v{report['version']} for {repo_full_name}")
            else:
                # New report
                report["previous_owners"] = []
                await db.reports.insert_one(report)
                logger.info(f"[NEW REPORT] Created v1 for {repo_full_name}")
            report.pop("_id", None)

            # Record credit transaction
            transaction_type = "upgrade" if is_upgrade else "generation"
            transaction_desc = f"Upgraded report for {repo_full_name} (v{report['version']})" if is_upgrade else f"Generated report for {repo_full_name}"
            
            await record_credit_transaction(
                user_id=uid,
                amount=-2,
                tx_type=transaction_type,
                reference_id=report_id,
                description=transaction_desc,
                timestamp=now
            )

            # Mark success — credits stay deducted
            credits_deducted = False

            updated_user = await db.users.find_one({"uid": uid}, {"_id": 0})
            total_duration = time.time() - start_time
            logger.info(f"[User:{uid}] [Repo:{repo_full_name}] [SUCCESS] Report generated in {total_duration:.2f}s")
            yield f"data: {json.dumps({'type': 'done', 'report_id': report_id, 'credits_remaining': updated_user.get('credits', 0)})}\n\n"

        except asyncio.CancelledError:
            duration = time.time() - start_time
            logger.warning(f"[User:{uid}] [Repo:{repo_full_name}] [CANCELLED] Client disconnected after {duration:.2f}s")
            # We don't yield here because the client is gone, but the finally block handles the refund
        except HTTPException as e:
            duration = time.time() - start_time
            logger.error(f"[User:{uid}] [Repo:{repo_full_name}] [HTTP ERROR] {e.detail} after {duration:.2f}s")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e.detail)})}\n\n"
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[User:{uid}] [Repo:{repo_full_name}] [ERROR] Generation failed after {duration:.2f}s: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Report generation failed. Credits have been refunded.'})}\n\n"
        finally:
            # Guaranteed refund if credits were deducted but report wasn't saved
            if credits_deducted:
                logger.info(f"[User:{uid}] [REFUND] Refunding 2 credits (generation failed or cancelled)")
                await db.users.update_one({"uid": uid}, {"$inc": {"credits": 2}})

    return StreamingResponse(stream_report(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


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

    async def stream_regen():
        credits_deducted = False
        try:
            await db.users.update_one(
                {"uid": uid},
                {"$inc": {"credits": -2}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            credits_deducted = True

            yield f"data: {json.dumps({'type': 'status', 'message': 'Re-fetching repository data...'})}\n\n"
            await db.github_cache.delete_one({"repo_full_name": existing["repo_full_name"]})
            github_data = await fetch_github_data(owner, repo)

            yield f"data: {json.dumps({'type': 'status', 'message': 'Regenerating report with AI...'})}\n\n"
            
            # Generate content with keepalive pings to prevent ingress timeout
            logger.info(f"Starting LLM regeneration for {existing['repo_full_name']} (user: {uid})")
            generation_task = asyncio.create_task(generate_report_content(github_data))
            ping_count = 0
            
            # Keep sending pings until generation completes
            while not generation_task.done():
                try:
                    # Wait up to 15 seconds for completion
                    content = await asyncio.wait_for(asyncio.shield(generation_task), timeout=15.0)
                    logger.info(f"LLM regeneration completed for {existing['repo_full_name']}")
                    break
                except asyncio.TimeoutError:
                    # Task still running - send keepalive ping
                    ping_count += 1
                    ping_msg = f"data: {json.dumps({'type': 'ping', 'message': f'Still processing... ({ping_count * 15}s elapsed)'})}\n\n"
                    logger.info(f"Sending keepalive ping #{ping_count} for regeneration (user: {uid})")
                    yield ping_msg
            
            # Get result if not already retrieved
            if not generation_task.done():
                content = await generation_task
            else:
                content = generation_task.result()

            logger.info(f"Regenerated content ready ({len(content)} chars) for {existing['repo_full_name']}")


            chunk_size = 40
            for i in range(0, len(content), chunk_size):
                yield f"data: {json.dumps({'type': 'content', 'text': content[i:i+chunk_size]})}\n\n"
                await asyncio.sleep(0.012)

            now = datetime.now(timezone.utc).isoformat()
            await db.reports.update_one({"id": report_id}, {"$set": {
                "content": content, "stars": github_data["repo_info"]["stargazers_count"],
                "forks": github_data["repo_info"]["forks_count"],
                "language": github_data["repo_info"]["language"] or "",
                "topics": github_data["repo_info"]["topics"],
                "updated_at": now, "version": existing.get("version", 1) + 1,
            }})

            await record_credit_transaction(
                user_id=uid,
                amount=-2,
                tx_type="regeneration",
                reference_id=report_id,
                description=f"Regenerated report for {existing['repo_full_name']}",
                timestamp=now
            )

            credits_deducted = False  # Success — keep deduction

            updated_user = await db.users.find_one({"uid": uid}, {"_id": 0})
            logger.info(f"[User:{uid}] [Repo:{existing['repo_full_name']}] [SUCCESS] Report regenerated")
            yield f"data: {json.dumps({'type': 'done', 'report_id': report_id, 'credits_remaining': updated_user.get('credits', 0)})}\n\n"
        except asyncio.CancelledError:
            logger.warning(f"[User:{uid}] [Repo:{existing['repo_full_name']}] [CANCELLED] Regeneration disconnected")
            # Client disconnected, let finally handle refund
        except Exception as e:
            logger.error(f"[User:{uid}] [Repo:{existing['repo_full_name']}] [ERROR] Regeneration failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Regeneration failed. Credits refunded.'})}\n\n"
        finally:
            if credits_deducted:
                logger.info(f"[User:{uid}] [REFUND] Refunding 2 credits (regeneration failed or cancelled)")
                await db.users.update_one({"uid": uid}, {"$inc": {"credits": 2}})

    return StreamingResponse(stream_regen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


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
    """Get version history for a report"""
    report = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not report:
        raise HTTPException(404, "Report not found")
    
    history = []
    
    # Add previous owners
    for prev_owner in report.get("previous_owners", []):
        history.append({
            "version": prev_owner.get("version", 0),
            "owner_name": prev_owner.get("user_name", "Unknown"),
            "owner_id": prev_owner.get("user_id"),
            "generated_at": prev_owner.get("generated_at"),
            "commit_sha": prev_owner.get("commit_sha", "")[:7]
        })
    
    # Add current owner
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
        user_id=user["uid"],
        amount=-1,
        tx_type="edit",
        reference_id=report_id,
        description=f"Edited report for {existing['repo_full_name']}",
        timestamp=now
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
        "id": str(uuid.uuid4()), "session_id": session.session_id,
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

    # Atomic update: only credit if payment_status transitions from non-paid to paid
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
                user_id=user["uid"],
                amount=credits_to_add,
                tx_type="purchase",
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
        logger.error(f"Webhook error: {e}")
        return {"status": "error"}


@api_router.get("/stats")
async def get_stats():
    total_reports = await db.reports.count_documents({})
    total_users = await db.users.count_documents({})
    return {"total_reports": total_reports, "total_users": total_users}


@api_router.get("/user/transactions")
async def get_user_transactions(user=Depends(get_current_user)):
    """Get payment and credit transaction history for the user"""
    payments = await db.payment_transactions.find(
        {"user_id": user["uid"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)

    credits = await db.credit_transactions.find(
        {"user_id": user["uid"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)

    return {"payments": payments, "credits": credits}



# Include router and middleware
app.include_router(api_router)

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
        # Users collection
        await db.users.create_index("uid", unique=True)
        
        # Reports collection
        await db.reports.create_index("id", unique=True)
        # await db.reports.create_index("repo_full_name")  # For lookup dedup
        await db.reports.create_index("generated_by")    # For user dashboard
        await db.reports.create_index([("generated_at", pymongo.DESCENDING)])
        
        # Transactions collections
        await db.payment_transactions.create_index("session_id", unique=True)
        await db.payment_transactions.create_index("user_id")
        await db.credit_transactions.create_index("user_id")
        await db.credit_transactions.create_index([("created_at", pymongo.DESCENDING)])
        
        # GitHub cache
        await db.github_cache.create_index("repo_full_name", unique=True)
        # Optional: TTL index to automatically clear old cache documents
        # await db.github_cache.create_index("fetched_at", expireAfterSeconds=GITHUB_CACHE_TTL)
        
        logger.info("Database indexes configured successfully.")
    except Exception as e:
        logger.error(f"Failed to create database indexes: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
