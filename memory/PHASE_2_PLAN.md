# Phase 2: Enterprise Organization Analysis - Implementation Plan

## Architecture Decisions

### ✅ Confirmed Choices
1. **GitHub Integration**: OAuth App (standard OAuth flow)
2. **Background Jobs**: Redis + Celery (production-grade)
3. **Pricing**: One-time payment ($50/$100/$200 based on repo count)
4. **Wiki Access**: Token-based (simple URL with access token)
5. **Implementation Order**: OAuth → Jobs → Wiki → Billing → Access

## Technical Stack

### Backend
- **Job Queue**: Redis 7.0
- **Worker**: Celery 5.6
- **GitHub Auth**: OAuth 2.0 flow
- **Storage**: MongoDB (organizations, jobs, wikis)

### Frontend
- **OAuth Flow**: GitHub OAuth redirect
- **Job Monitoring**: Real-time progress via polling/WebSocket
- **Wiki Viewer**: Markdown rendering with access control

## Database Schema

### organizations
```javascript
{
  id: "uuid",
  github_org_id: 12345,
  github_org_login: "facebook",
  github_org_name: "Facebook Open Source",
  avatar_url: "https://avatars.githubusercontent.com/u/69631",
  
  // Access & Ownership
  owner_user_id: "user-uuid",
  access_token: "encrypted-github-token",
  access_token_expires: "2025-12-31T00:00:00Z",
  
  // Repo Analysis
  total_repos: 150,
  analyzed_repos: 0,
  last_analyzed_at: null,
  
  // Wiki
  wiki_id: "wiki-uuid",
  wiki_access_token: "random-secure-token",
  wiki_url: "/wiki/facebook/access-token",
  
  // Billing
  pricing_tier: "medium", // small (0-50), medium (50-100), large (100+)
  payment_status: "pending" | "paid" | "failed",
  stripe_session_id: "cs_...",
  paid_amount: 100,
  
  // Metadata
  created_at: "2025-02-21T00:00:00Z",
  updated_at: "2025-02-21T00:00:00Z"
}
```

### analysis_jobs
```javascript
{
  id: "uuid",
  organization_id: "org-uuid",
  user_id: "user-uuid",
  
  // Job Details
  job_type: "full_analysis" | "incremental_update",
  status: "queued" | "processing" | "completed" | "failed",
  
  // Progress Tracking
  total_repos: 50,
  processed_repos: 25,
  failed_repos: 2,
  progress_percentage: 50,
  
  // Timing
  started_at: "2025-02-21T10:00:00Z",
  completed_at: null,
  estimated_completion: "2025-02-21T10:45:00Z",
  
  // Results
  generated_reports: ["report-id-1", "report-id-2", ...],
  failed_repo_names: ["private-repo", "archived-repo"],
  wiki_id: "wiki-uuid",
  
  // Error Handling
  error_message: null,
  retry_count: 0,
  
  // Metadata
  created_at: "2025-02-21T09:00:00Z",
  updated_at: "2025-02-21T10:15:00Z"
}
```

### organization_wikis
```javascript
{
  id: "uuid",
  organization_id: "org-uuid",
  access_token: "random-secure-token",
  
  // Wiki Content
  overview_content: "# Facebook Organization Overview...",
  repo_reports: [
    { repo_name: "react", report_id: "report-uuid-1" },
    { repo_name: "jest", report_id: "report-uuid-2" }
  ],
  
  // Cross-Repo Analysis
  tech_stack_summary: {
    languages: {"JavaScript": 45, "TypeScript": 30, "Python": 25},
    frameworks: {"React": 15, "Next.js": 8, "Express": 12},
    databases: {"PostgreSQL": 5, "MongoDB": 3}
  },
  
  // Metadata
  total_repos_analyzed: 50,
  last_updated_at: "2025-02-21T11:00:00Z",
  generated_at: "2025-02-21T10:00:00Z"
}
```

## API Endpoints

### GitHub OAuth
```
GET  /api/enterprise/github/authorize
     → Redirect to GitHub OAuth

GET  /api/enterprise/github/callback?code=...
     → Exchange code for token, fetch orgs, redirect to dashboard

POST /api/enterprise/organizations/connect
     → Connect specific organization for analysis
     Body: { github_org_id, github_org_login }
```

### Organization Management
```
GET  /api/enterprise/organizations
     → List user's connected organizations

GET  /api/enterprise/organizations/{org_id}
     → Get organization details

DELETE /api/enterprise/organizations/{org_id}
     → Disconnect organization
```

### Analysis Jobs
```
POST /api/enterprise/organizations/{org_id}/analyze
     → Start background analysis job
     → Creates Stripe checkout for payment

GET  /api/enterprise/jobs/{job_id}
     → Get job status and progress

GET  /api/enterprise/jobs/{job_id}/progress
     → Real-time progress updates (polling endpoint)
```

### Organization Wikis
```
GET  /wiki/{org_login}/{access_token}
     → Public wiki viewer (no auth required, just valid token)

GET  /api/enterprise/wikis/{wiki_id}
     → Get wiki content (for authorized users)

POST /api/enterprise/wikis/{wiki_id}/regenerate-token
     → Generate new access token (invalidates old one)
```

## Celery Tasks

### Task: analyze_organization
```python
@celery_app.task(bind=True)
def analyze_organization(self, job_id: str, organization_id: str):
    """
    Analyze all repositories in an organization.
    Updates job progress in real-time.
    """
    job = get_job(job_id)
    org = get_organization(organization_id)
    
    # Fetch all repos from GitHub
    repos = fetch_organization_repos(org.access_token, org.github_org_login)
    
    total = len(repos)
    update_job(job_id, total_repos=total, status="processing")
    
    reports = []
    failed = []
    
    for i, repo in enumerate(repos):
        try:
            # Generate report for each repo
            report = generate_repo_report(repo)
            reports.append(report)
        except Exception as e:
            failed.append(repo['name'])
            log_error(f"Failed to analyze {repo['name']}: {e}")
        
        # Update progress
        progress = ((i + 1) / total) * 100
        update_job(job_id, processed_repos=i+1, progress_percentage=progress)
        
        # Update task state (for Celery monitoring)
        self.update_state(
            state='PROGRESS',
            meta={'current': i+1, 'total': total, 'progress': progress}
        )
    
    # Generate organization overview wiki
    wiki = generate_organization_wiki(org, reports)
    
    # Mark job as complete
    update_job(job_id,
        status="completed",
        generated_reports=[r['id'] for r in reports],
        failed_repo_names=failed,
        wiki_id=wiki['id'],
        completed_at=datetime.now()
    )
```

## Frontend Pages

### /enterprise
- Landing page explaining enterprise features
- "Connect GitHub Organization" button
- Pricing table ($50/$100/$200)

### /enterprise/organizations
- List of connected organizations
- Status: Not Analyzed, Analyzing (progress), Analyzed
- "Start Analysis" button
- "View Wiki" link (if analyzed)

### /enterprise/organizations/{id}
- Organization details
- List of repos
- Analysis progress (if running)
- "Start Analysis" / "Re-analyze" button

### /wiki/{org_login}/{access_token}
- Public wiki viewer (no login required)
- Organization overview
- List of all repo reports
- Tech stack summary
- Cross-repo architecture diagrams
- Share button (copy link)

## Implementation Phases

### Phase 2.1: GitHub OAuth & Organization Setup (Day 1-2)
- [ ] Create GitHub OAuth App configuration
- [ ] Implement OAuth endpoints
- [ ] Frontend: Connect organization flow
- [ ] Store organization data
- [ ] Fetch organization repos

### Phase 2.2: Background Job System (Day 2-3)
- [ ] Configure Celery with Redis
- [ ] Create job models in MongoDB
- [ ] Implement analyze_organization task
- [ ] Progress tracking endpoints
- [ ] Frontend: Job progress UI

### Phase 2.3: Wiki Generation (Day 3-4)
- [ ] Generate individual repo reports
- [ ] Create organization overview
- [ ] Tech stack summary across repos
- [ ] Cross-repo analysis (common patterns)
- [ ] Store wiki content

### Phase 2.4: Pricing & Billing (Day 4-5)
- [ ] Calculate pricing based on repo count
- [ ] Stripe checkout integration
- [ ] Payment verification
- [ ] Unlock analysis after payment

### Phase 2.5: Wiki Access & Sharing (Day 5)
- [ ] Token-based wiki viewer
- [ ] Public wiki page
- [ ] Regenerate access token
- [ ] Share functionality

## Success Metrics

- Organization connection time: <30 seconds
- Analysis completion time: <5 minutes per 10 repos
- Wiki generation: <1 minute after all reports done
- Payment success rate: >95%

## Next Steps

Starting with Phase 2.1: GitHub OAuth Integration
