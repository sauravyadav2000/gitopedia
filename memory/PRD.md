# Gitopedia - Product Requirements Document

## Overview
Gitopedia is a GitHub repository intelligence tool that uses AI to generate comprehensive technical reports. The platform has evolved from a simple report generator to a community-driven maintenance platform where reports stay fresh through collaborative upgrades.

## Core Features

### 1. Report Generation (Original Feature)
- **What**: Users submit a GitHub repository URL and receive an AI-generated technical report
- **LLM**: Claude Haiku (fast mode, 15-40s) with fallback to Claude Sonnet 4
- **Cost**: 2 credits per report generation
- **Output**: Rich Markdown with Mermaid diagrams, tech stack analysis, architecture overview

### 2. Credit System (Original Feature)
- **Free Credits**: 3 credits on signup
- **Pricing**:
  - $2 for 5 credits
  - $5 for 15 credits
  - $10 for 35 credits
- **Transactions**: Full history visible in user dashboard
- **Refund Policy**: Automatic refund on generation failure

### 3. Report Ownership & Upgrade System (Phase 1 - ✅ COMPLETED)
**Problem**: Reports become outdated as repositories evolve  
**Solution**: Collaborative maintenance model where any user can upgrade stale reports

#### How It Works:
1. **Initial Generation**: User generates report → Becomes owner (v1)
2. **Aging**: Report ages over time
3. **Upgrade Eligibility**: Report can be upgraded if:
   - Report is >30 days old AND
   - Repository has new commits since last generation
4. **Upgrade Process**: 
   - Any logged-in user can upgrade for 2 credits
   - Upgrader becomes new owner
   - Previous owner moved to version history
   - Version number increments (v1 → v2 → v3...)

#### User Benefits:
- **For Community**: Fresh, up-to-date reports
- **For Upgraders**: Ownership of popular repository reports
- **For Platform**: Content stays current without manual intervention

#### Technical Implementation:
**Backend**:
- `check_repo_freshness()` - Compares report age and GitHub commits
- `/api/reports/check` - Returns upgrade eligibility
- `/api/reports/generate` - Handles both new and upgrade generations
- `/api/reports/{id}/history` - Version history endpoint

**Frontend**:
- `OwnershipBanner` - Shows current maintainer
- `UpgradeAlert` - Displays when report is outdated
- `VersionHistory` - Accordion showing all previous owners

**Database Fields**:
- `current_owner_id`, `current_owner_name` - Current maintainer
- `version` - Increments with each upgrade
- `previous_owners` - Array of version history
- `repo_last_commit_sha` - Latest commit when generated

### 4. Firebase Authentication (Original Feature)
- **Provider**: Firebase Auth
- **Features**: Email/password registration and login
- **User Data**: Display name, email, credits, transaction history

### 5. Stripe Payment Integration (Original Feature)
- **Provider**: Stripe Checkout
- **Flow**: 
  1. User selects credit package
  2. Redirected to Stripe checkout
  3. On success, credits added to account
  4. Transaction recorded in database
- **Idempotency**: Prevents double-crediting via session ID checks

### 6. Advanced Report Features (Original Feature)
- **Mermaid Diagrams**: Architecture diagrams, sequence diagrams, ER diagrams
- **Directory Tree**: ASCII representation of repo structure
- **Tech Stack Analysis**: Detects frameworks, languages, dependencies
- **Streaming Output**: Real-time report generation via SSE
- **Optimized Context**: Filters out build artifacts, binaries, test folders

## Planned Features

### Phase 2: Enterprise Organization Analysis (PLANNED)
**What**: Users connect their GitHub organizations and get comprehensive wikis

#### Features:
- **Organization Integration**: GitHub OAuth for org access
- **Bulk Analysis**: Analyze all repos in an organization
- **Organization Wiki**: 
  - Individual repo reports
  - Cross-repo architecture diagrams
  - Tech stack summary
  - Common patterns across repos
- **Access Control**: Wiki is private to org members
- **Pricing**: Based on repo count (e.g., $50/month for 0-50 repos)
- **Long-Running Jobs**: Background job queue (Redis + Celery)
- **Progress Tracking**: Real-time dashboard showing analysis status

#### Technical Requirements:
- Background job system (Celery/RQ + Redis)
- GitHub OAuth integration
- Organization-level authentication
- Wiki generation and hosting
- Job queue management
- Email notifications on completion

## Technical Architecture

### Frontend
- **Framework**: React 18
- **Routing**: React Router v6
- **Styling**: Tailwind CSS + Shadcn UI
- **State**: React Context API
- **Auth**: Firebase SDK
- **Payments**: Stripe.js
- **Real-time**: EventSource (SSE)
- **Diagrams**: Mermaid.js
- **Animations**: Framer Motion

### Backend
- **Framework**: FastAPI (Python 3.11+)
- **Database**: MongoDB (Motor async driver)
- **Authentication**: Firebase Admin SDK
- **Payments**: Stripe Python SDK
- **LLM**: Anthropic SDK (Claude)
  - Primary: Claude Haiku (fast)
  - Fallback: Claude Sonnet 4 (quality)
  - Alternative: Emergent LLM Key
- **GitHub Integration**: GitHub REST API
- **Streaming**: Server-Sent Events (SSE)
- **Background Jobs**: (Phase 2) Celery + Redis

### Database Schema

#### users
```javascript
{
  uid: "firebase-uid",
  email: "user@example.com",
  display_name: "John Doe",
  credits: 5,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-02-01T00:00:00Z"
}
```

#### reports (Updated with Phase 1 fields)
```javascript
{
  id: "uuid",
  repo_full_name: "facebook/react",
  repo_url: "https://github.com/facebook/react",
  title: "React",
  description: "A JavaScript library for building user interfaces",
  content: "# React Analysis...",
  language: "JavaScript",
  stars: 225000,
  forks: 45000,
  topics: ["javascript", "react", "frontend"],
  
  // Ownership fields (Phase 1)
  current_owner_id: "user-uuid",
  current_owner_name: "Alice Smith",
  version: 3,
  previous_owners: [
    { user_id: "...", user_name: "Bob", generated_at: "...", version: 1, commit_sha: "..." },
    { user_id: "...", user_name: "Charlie", generated_at: "...", version: 2, commit_sha: "..." }
  ],
  
  // Freshness tracking (Phase 1)
  repo_last_commit_sha: "abc123def456",
  repo_last_commit_date: "2025-02-20T15:30:00Z",
  
  // Original fields
  generated_by: "user-uuid",
  generated_at: "2025-02-20T10:00:00Z",
  updated_at: "2025-02-20T10:05:00Z"
}
```

#### transactions
```javascript
{
  id: "uuid",
  user_id: "user-uuid",
  amount: -2,
  type: "generation" | "upgrade" | "edit" | "purchase",
  reference_id: "report-id" | "session-id",
  description: "Generated report for facebook/react",
  created_at: "2025-02-01T00:00:00Z",
  
  // For purchases
  stripe_session_id: "cs_...",
  credits_purchased: 5,
  payment_status: "succeeded"
}
```

#### github_cache
```javascript
{
  repo_full_name: "facebook/react",
  data: { /* GitHub API response */ },
  fetched_at: "2025-02-01T00:00:00Z"
}
```

## API Endpoints

### Authentication
- `POST /api/auth/verify` - Verify Firebase token, create/update user
- `GET /api/user/profile` - Get user profile with credits

### Reports
- `POST /api/reports/check` - Check if report exists and upgrade eligibility
- `POST /api/reports/generate` - Generate new report or upgrade existing (SSE)
- `GET /api/reports/{id}` - Get single report
- `GET /api/reports/{id}/history` - Get version history (Phase 1)
- `PUT /api/reports/{id}` - Edit report (1 credit)
- `POST /api/reports/{id}/regenerate` - Regenerate report (2 credits, SSE)
- `GET /api/reports` - List/search reports
- `GET /api/user/reports` - Get user's reports

### Credits & Payments
- `GET /api/credits/packages` - Get available credit packages
- `POST /api/credits/checkout` - Create Stripe checkout session
- `GET /api/credits/checkout/status/{session_id}` - Check payment status
- `POST /api/webhook/stripe` - Stripe webhook handler
- `GET /api/user/transactions` - Get user's transaction history

### Public
- `GET /api/stats` - Public statistics (total reports, users)

## Key Metrics & Success Criteria

### Platform Health
- Average report generation time: <45 seconds (Claude Haiku)
- Report freshness: % of reports <30 days old
- Credit refund rate: <5% (low failure rate)

### User Engagement
- Signup → First generation conversion: >60%
- Credit purchase conversion: >20%
- Report upgrade rate: % of outdated reports upgraded within 60 days

### Community Metrics (Phase 1)
- Average report ownership duration
- Number of active maintainers
- Popular repos: Reports with 5+ upgrades
- Top maintainers: Users maintaining 10+ reports

## Known Limitations

### Infrastructure
- **60-second ingress timeout**: Kubernetes nginx ingress drops SSE connections after 60s
  - **Workaround**: SSE keepalive pings every 15s
  - **Status**: Mitigated but not fully resolved
  - **Long-term**: Requires platform-level ingress configuration

### LLM Generation
- **Large repositories**: Repos with 10,000+ files may still approach timeout
  - **Mitigation**: Aggressive file filtering, faster model (Haiku)
  - **Context limit**: 200K tokens (Anthropic limit)

### GitHub API
- **Rate limits**: 60 requests/hour unauthenticated, 5,000 authenticated
  - **Mitigation**: Caching, strategic endpoint selection
  - **Future**: GitHub App for higher limits

## Security & Privacy
- **Authentication**: Firebase tokens verified on every request
- **Data Privacy**: Only public GitHub repositories supported
- **Payment Security**: Stripe handles all payment processing (PCI compliant)
- **API Keys**: Stored securely in environment variables
- **Credit Transactions**: Atomic operations with refund guarantees

## Development Status

### ✅ Completed (MVP + Phase 1)
- User authentication (Firebase)
- Credit system with Stripe payments
- AI-powered report generation (Claude)
- SSE streaming with keepalive
- Report editing
- Transaction history
- **Phase 1**: Report ownership & upgrade system
- **Phase 1**: Version history tracking
- **Phase 1**: Freshness checking
- **Phase 1**: Ownership UI components

### 🚧 In Progress
- None (Phase 1 complete)

### 📋 Planned (Phase 2)
- Enterprise organization analysis
- Background job queue
- Organization wikis
- Cross-repo architecture diagrams
- Email notifications
- Admin dashboard

## Version History
- **v1.0** (Jan 2025): Initial MVP - Report generation, credits, payments
- **v1.1** (Feb 2025): Bug fixes - Auth race condition, double-crediting, credit refunds
- **v1.2** (Feb 2025): Performance - LLM speed optimization (Claude Haiku), context filtering
- **v2.0** (Feb 2025): Phase 1 - Report ownership & upgrade system ✅
- **v3.0** (Planned): Phase 2 - Enterprise organization analysis
