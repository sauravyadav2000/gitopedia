"""
Background tasks for organization analysis
"""
from celery_config import celery_app
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
import asyncio
import httpx
import os
import logging

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

logger = logging.getLogger(__name__)

# MongoDB connection
mongo_client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = mongo_client[os.environ['DB_NAME']]


@celery_app.task(bind=True, name='analyze_organization')
def analyze_organization(self, job_id: str, organization_id: str, github_token: str):
    """
    Analyze all repositories in an organization.
    This is a long-running task that generates reports for each repo.
    """
    return asyncio.run(_analyze_organization_async(self, job_id, organization_id, github_token))


async def _analyze_organization_async(task, job_id: str, organization_id: str, github_token: str):
    """Async implementation of organization analysis"""
    try:
        # Get organization and job details
        org = await db.organizations.find_one({"id": organization_id}, {"_id": 0})
        if not org:
            raise Exception(f"Organization {organization_id} not found")
        
        # Update job status to processing
        await db.analysis_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "processing",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        # Fetch all repositories from GitHub
        logger.info(f"[JOB {job_id}] Fetching repos for org: {org['github_org_login']}")
        repos = await fetch_organization_repos(github_token, org['github_org_login'])
        
        total_repos = len(repos)
        logger.info(f"[JOB {job_id}] Found {total_repos} repositories")
        
        # Update total repos count
        await db.analysis_jobs.update_one(
            {"id": job_id},
            {"$set": {"total_repos": total_repos}}
        )
        
        # Process each repository
        generated_reports = []
        failed_repos = []
        
        for i, repo in enumerate(repos):
            try:
                logger.info(f"[JOB {job_id}] Processing repo {i+1}/{total_repos}: {repo['full_name']}")
                
                # Skip private repos (not supported yet)
                if repo.get('private'):
                    logger.warning(f"[JOB {job_id}] Skipping private repo: {repo['full_name']}")
                    failed_repos.append(repo['full_name'])
                    continue
                
                # Generate report for this repo
                # Check if report already exists
                existing = await db.reports.find_one({"repo_full_name": repo['full_name']}, {"_id": 0})
                
                if existing:
                    # Use existing report
                    generated_reports.append(existing['id'])
                    logger.info(f"[JOB {job_id}] Using existing report for {repo['full_name']}")
                else:
                    # TODO: Generate new report (will implement in next step)
                    logger.info(f"[JOB {job_id}] Would generate report for {repo['full_name']}")
                    # For now, skip generation
                    pass
                
                # Update progress
                processed = i + 1
                progress = (processed / total_repos) * 100
                
                await db.analysis_jobs.update_one(
                    {"id": job_id},
                    {"$set": {
                        "processed_repos": processed,
                        "progress_percentage": round(progress, 2),
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                
                # Update Celery task state
                task.update_state(
                    state='PROGRESS',
                    meta={
                        'current': processed,
                        'total': total_repos,
                        'progress': round(progress, 2),
                        'current_repo': repo['full_name']
                    }
                )
                
            except Exception as e:
                logger.error(f"[JOB {job_id}] Failed to process {repo['full_name']}: {e}")
                failed_repos.append(repo['full_name'])
        
        # Generate organization wiki
        logger.info(f"[JOB {job_id}] Generating organization wiki")
        wiki = await generate_organization_wiki(organization_id, org, generated_reports, repos)
        
        # Mark job as completed
        await db.analysis_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "generated_reports": generated_reports,
                "failed_repo_names": failed_repos,
                "wiki_id": wiki['id'],
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        logger.info(f"[JOB {job_id}] Analysis completed! Generated {len(generated_reports)} reports, {len(failed_repos)} failed")
        
        return {
            "job_id": job_id,
            "status": "completed",
            "total_repos": total_repos,
            "successful": len(generated_reports),
            "failed": len(failed_repos),
            "wiki_id": wiki['id']
        }
        
    except Exception as e:
        logger.error(f"[JOB {job_id}] Fatal error: {e}")
        
        # Mark job as failed
        await db.analysis_jobs.update_one(
            {"id": job_id},
            {"$set": {
                "status": "failed",
                "error_message": str(e),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        raise


async def fetch_organization_repos(github_token: str, org_login: str):
    """Fetch all repositories for an organization from GitHub"""
    repos = []
    page = 1
    per_page = 100
    
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                resp = await client.get(
                    f"https://api.github.com/orgs/{org_login}/repos",
                    headers={
                        "Authorization": f"Bearer {github_token}",
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "Gitopedia/1.0"
                    },
                    params={"page": page, "per_page": per_page, "sort": "updated"}
                )
                
                if resp.status_code != 200:
                    logger.error(f"GitHub API error: {resp.status_code} - {resp.text}")
                    break
                
                batch = resp.json()
                if not batch:
                    break
                
                repos.extend(batch)
                page += 1
                
                # Safety limit: max 500 repos
                if len(repos) >= 500:
                    break
                    
            except Exception as e:
                logger.error(f"Error fetching repos: {e}")
                break
    
    return repos


async def generate_organization_wiki(org_id: str, org: dict, report_ids: list, repos: list):
    """Generate organization wiki with overview and cross-repo analysis"""
    from uuid import uuid4
    import secrets
    
    wiki_id = str(uuid4())
    access_token = secrets.token_urlsafe(32)
    
    # Calculate tech stack summary
    tech_stack = {}
    for repo in repos:
        lang = repo.get('language')
        if lang:
            tech_stack[lang] = tech_stack.get(lang, 0) + 1
    
    # Create overview content
    overview = f"""# {org['github_org_name']} - Organization Overview

## Summary
- **Total Repositories**: {len(repos)}
- **Analyzed Repositories**: {len(report_ids)}
- **Primary Languages**: {', '.join(sorted(tech_stack.keys(), key=lambda x: tech_stack[x], reverse=True)[:5])}

## Technology Stack
{chr(10).join(f"- **{lang}**: {count} repositories" for lang, count in sorted(tech_stack.items(), key=lambda x: x[1], reverse=True)[:10])}

## Repositories

{chr(10).join(f"### [{repo['name']}]({repo['html_url']})" + chr(10) + f"{repo.get('description', 'No description')}" + chr(10) for repo in repos[:20])}

---

*Generated by Gitopedia on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*
"""
    
    wiki = {
        "id": wiki_id,
        "organization_id": org_id,
        "access_token": access_token,
        "overview_content": overview,
        "repo_reports": [{"repo_name": r['name'], "report_id": rid} for r, rid in zip(repos[:len(report_ids)], report_ids)],
        "tech_stack_summary": tech_stack,
        "total_repos_analyzed": len(report_ids),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.organization_wikis.insert_one(wiki)
    
    # Update organization with wiki info
    await db.organizations.update_one(
        {"id": org_id},
        {"$set": {
            "wiki_id": wiki_id,
            "wiki_access_token": access_token,
            "wiki_url": f"/wiki/{org['github_org_login']}/{access_token}",
            "analyzed_repos": len(report_ids),
            "last_analyzed_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return wiki
