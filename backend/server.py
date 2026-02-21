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
mongo_url = os.environ['MONGO_URL']
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ['DB_NAME']]

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


async def fetch_github_data(owner: str, repo: str) -> dict:
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
            except:
                readme_content = "Unable to decode README"

        file_tree = []
        if not isinstance(tree_resp, Exception) and tree_resp.status_code == 200:
            tree_data = tree_resp.json()
            for item in (tree_data.get("tree") or [])[:500]:
                if item.get("size", 0) > 1048576:
                    file_tree.append(f"{item['path']} (file too large to analyze)")
                else:
                    file_tree.append(item["path"])

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
                    "message": commit.get("message", "")[:200],
                    "author": commit.get("author", {}).get("name"),
                    "date": commit.get("author", {}).get("date"),
                })

        # Fetch key config files
        config_files = {}
        key_files = ["package.json", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml",
                      "Dockerfile", "docker-compose.yml", "Makefile", "tsconfig.json", "pyproject.toml"]
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
            except:
                pass

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
    tree_str = "\n".join(data["file_tree"][:200])
    if len(data["file_tree"]) > 200:
        tree_str += f"\n... and {len(data['file_tree']) - 200} more files"
    configs_str = ""
    for fp, content in data["config_files"].items():
        configs_str += f"\n### {fp}\n```\n{content}\n```\n"
    contribs_str = "\n".join([f"- {c['login']}: {c['contributions']} contributions" for c in data["contributors"]])
    commits_str = "\n".join([
        f"- [{c['date'][:10] if c['date'] else 'N/A'}] {c['author']}: {c['message']}"
        for c in data["recent_commits"]
    ])

    return f"""Analyze the following GitHub repository data and generate a comprehensive Markdown report.

## Repository Information
- Name: {repo['full_name']}
- Description: {repo['description'] or 'No description'}
- Primary Language: {repo['language'] or 'N/A'}
- Stars: {repo['stargazers_count']} | Forks: {repo['forks_count']} | Open Issues: {repo['open_issues_count']}
- Created: {repo['created_at']} | Last Updated: {repo['pushed_at']}
- Default Branch: {repo['default_branch']} | License: {repo['license'] or 'Not specified'}
- Topics: {', '.join(repo['topics']) if repo['topics'] else 'None'}
- Size: {repo['size']} KB

## Languages
{languages_str or 'No language data'}

## File Structure
{tree_str or 'Unable to retrieve'}

## README
{data['readme'] or 'No README found'}

## Configuration Files
{configs_str or 'None found'}

## Top Contributors
{contribs_str or 'No data'}

## Recent Commits
{commits_str or 'No data'}

---
Generate a report with EXACTLY these sections. Start directly with ## Overview:

## Overview
3-4 sentences summarizing what this repository is, its purpose, and significance.

## Tech Stack
A markdown table with columns: Layer | Technology | Purpose
Cover: Language(s), Framework(s), Database(s), Infrastructure, Testing, CI/CD, Package Manager.
Only include what's confirmed by the data.

## Repository Structure
Explain the directory layout in prose.

## Architecture & Design
How is the system designed? Patterns, principles, structure.

## Service Communication & Dependencies
How do components communicate? APIs, queues, shared state.

## Infrastructure & Deployment
How is this deployed? CI/CD, containers, cloud services.

## Development Workflow
How to run locally? Setup steps from config files.

## Key Observations
3-5 bullet points of the most important things to know.

## Repo Health
A markdown table: Metric | Value
Include: Stars, Forks, Open Issues, Last Updated, License, Primary Language, Contributors Count.

RULES:
- Only include facts supported by the data. Do NOT fabricate.
- If a section can't be determined, say "Insufficient data to determine."
- Use proper Markdown: tables, bullets, code blocks.
- Be thorough but concise. No preamble."""


async def generate_report_content(data: dict) -> str:
    prompt = build_report_prompt(data)
    system_msg = "You are an expert software architect and technical writer. You analyze GitHub repositories and produce detailed, accurate technical reports. Your reports are clear, well-structured, and highly valuable to developers."

    # Priority 1: Direct Anthropic API key
    anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
    if anthropic_key:
        try:
            logger.info("Using direct Anthropic API key for generation")
            client = anthropic.AsyncAnthropic(api_key=anthropic_key)
            message = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8000,
                system=system_msg,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
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

    existing = await db.users.find_one({"uid": uid}, {"_id": 0})
    if existing:
        return existing

    now = datetime.now(timezone.utc).isoformat()
    user = {"uid": uid, "email": email, "display_name": name, "credits": 3, "created_at": now, "updated_at": now}
    await db.users.insert_one(user)
    user.pop("_id", None)
    return user


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
    if existing:
        return {"exists": True, "report": existing}
    return {"exists": False}


@api_router.post("/reports/generate")
async def generate_report(req: GenerateRequest, user=Depends(get_current_user)):
    try:
        owner, repo = parse_repo_url(req.repo_url)
    except ValueError:
        raise HTTPException(400, "Invalid GitHub URL")

    repo_full_name = f"{owner}/{repo}"

    # Dedup check
    existing = await db.reports.find_one({"repo_full_name": repo_full_name}, {"_id": 0})
    if existing:
        return {
            "exists": True,
            "report": existing,
            "message": "A report for this repo already exists. View it for free or spend 2 credits to regenerate with latest data."
        }

    # Ensure user exists in DB (race condition: generate can fire before auth/verify completes)
    user_doc = await db.users.find_one({"uid": user["uid"]}, {"_id": 0})
    if not user_doc:
        now = datetime.now(timezone.utc).isoformat()
        user_doc = {
            "uid": user["uid"], "email": user.get("email", ""),
            "display_name": user.get("name", user.get("email", "User").split("@")[0]),
            "credits": 3, "created_at": now, "updated_at": now,
        }
        await db.users.insert_one(user_doc)
        user_doc.pop("_id", None)

    if user_doc.get("credits", 0) < 2:
        raise HTTPException(402, "Insufficient credits. You need 2 credits to generate a report.")

    uid = user["uid"]

    async def stream_report():
        credits_deducted = False
        try:
            # Deduct credits INSIDE the stream so refund is guaranteed by finally
            await db.users.update_one(
                {"uid": uid},
                {"$inc": {"credits": -2}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            )
            credits_deducted = True

            yield f"data: {json.dumps({'type': 'status', 'message': 'Fetching repository data from GitHub...'})}\n\n"
            github_data = await fetch_github_data(owner, repo)

            yield f"data: {json.dumps({'type': 'status', 'message': 'Analyzing codebase with AI...'})}\n\n"
            content = await generate_report_content(github_data)

            yield f"data: {json.dumps({'type': 'status', 'message': 'Streaming report...'})}\n\n"

            chunk_size = 40
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'content', 'text': chunk})}\n\n"
                await asyncio.sleep(0.012)

            # Save report
            report_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
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
                "generated_by": uid,
                "generated_at": now,
                "updated_at": now,
                "version": 1,
            }
            await db.reports.insert_one(report)
            report.pop("_id", None)

            await db.credit_transactions.insert_one({
                "id": str(uuid.uuid4()), "user_id": uid, "amount": -2,
                "type": "generation", "reference_id": report_id,
                "description": f"Generated report for {repo_full_name}", "created_at": now,
            })

            # Mark success — credits stay deducted
            credits_deducted = False

            updated_user = await db.users.find_one({"uid": uid}, {"_id": 0})
            yield f"data: {json.dumps({'type': 'done', 'report_id': report_id, 'credits_remaining': updated_user.get('credits', 0)})}\n\n"

        except HTTPException as e:
            logger.error(f"Report generation HTTP error: {e.detail}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e.detail)})}\n\n"
        except Exception as e:
            logger.error(f"Report generation error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Report generation failed. Credits have been refunded.'})}\n\n"
        finally:
            # Guaranteed refund if credits were deducted but report wasn't saved
            if credits_deducted:
                logger.info(f"Refunding 2 credits for user {uid} (generation failed)")
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
            content = await generate_report_content(github_data)

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

            await db.credit_transactions.insert_one({
                "id": str(uuid.uuid4()), "user_id": uid, "amount": -2,
                "type": "regeneration", "reference_id": report_id,
                "description": f"Regenerated report for {existing['repo_full_name']}", "created_at": now,
            })

            credits_deducted = False  # Success — keep deduction

            updated_user = await db.users.find_one({"uid": uid}, {"_id": 0})
            yield f"data: {json.dumps({'type': 'done', 'report_id': report_id, 'credits_remaining': updated_user.get('credits', 0)})}\n\n"
        except Exception as e:
            logger.error(f"Regeneration error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Regeneration failed. Credits refunded.'})}\n\n"
        finally:
            if credits_deducted:
                logger.info(f"Refunding 2 credits for user {uid} (regeneration failed)")
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

    await db.credit_transactions.insert_one({
        "id": str(uuid.uuid4()), "user_id": user["uid"], "amount": -1,
        "type": "edit", "reference_id": report_id,
        "description": f"Edited report for {existing['repo_full_name']}", "created_at": now,
    })

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

    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if tx and status.payment_status == "paid" and tx.get("payment_status") != "paid":
        now = datetime.now(timezone.utc).isoformat()
        credits_to_add = tx.get("credits", 0)
        await db.users.update_one(
            {"uid": user["uid"]},
            {"$inc": {"credits": credits_to_add}, "$set": {"updated_at": now}}
        )
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"status": "complete", "payment_status": "paid", "updated_at": now}}
        )
        await db.credit_transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": user["uid"], "amount": credits_to_add,
            "type": "purchase", "reference_id": tx.get("id"),
            "description": f"Purchased {credits_to_add} credits ({tx.get('package_id')} package)", "created_at": now,
        })
    elif tx:
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


# Include router and middleware
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
