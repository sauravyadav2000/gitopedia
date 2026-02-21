# Gitopedia - Product Requirements Document

## Original Problem Statement
Build a full-stack web application called "Gitopedia" — a GitHub repository intelligence tool that generates structured Markdown reports about any public GitHub repository using the GitHub API and Claude LLM. Community-driven: generating and editing reports costs credits, reading is free for everyone.

## Architecture
- **Backend**: FastAPI + MongoDB + Firebase Admin SDK + Claude Sonnet 4.6 (via Emergent) + Stripe
- **Frontend**: React + Firebase Auth + Shadcn UI + react-markdown + SSE streaming + Framer Motion
- **Database**: MongoDB (local)
- **Auth**: Firebase email/password
- **Payments**: Stripe (test mode)
- **LLM**: Claude Sonnet 4.6 via Emergent integrations library

## User Personas
1. **Developer/Contributor** - Wants to understand a repo before contributing
2. **Engineering Manager** - Evaluates technology choices and architecture
3. **Tech Recruiter** - Assesses project quality and developer competency
4. **Open Source Explorer** - Discovers and learns about interesting projects

## Core Requirements
- Users paste a GitHub repo URL
- System fetches repo data via GitHub REST API
- Sends structured context to Claude Sonnet 4.6
- Generates a structured Markdown report with specific sections
- Saves and publishes the report publicly
- Anyone can read it for free
- Paid/credit users can regenerate, edit, or customize

## Credit System
- Signup: 3 free credits
- Generate report: 2 credits
- Edit & republish: 1 credit
- Read: FREE
- Buy: $2/5 credits, $5/15 credits, $10/35 credits (Stripe)

## What's Been Implemented (Phase 1 - Feb 2026)
### Backend
- Firebase auth token verification + user creation with 3 free credits (upsert, race-safe)
- User profile, reports, and transaction history endpoints
- GitHub data fetching (repo info, README, file tree, languages, contributors, commits, config files)
- GitHub data caching in MongoDB (1 hour TTL)
- Claude report generation with **deeply enhanced prompt** — Mermaid diagrams, directory trees, security/dependency/code quality analysis
- Direct Anthropic API key support with Emergent LLM fallback
- SSE streaming for real-time report delivery
- Report CRUD: check, generate, list/search, get, edit, regenerate
- Credit deduction with **guaranteed refund** via finally block
- **Atomic** Stripe checkout with find_one_and_update (prevents double-crediting)
- Stripe webhook handling
- Report deduplication by repo_full_name (unique index)
- Private repo detection, file size handling (>1MB skip)
- Unique indexes on users.uid and reports.repo_full_name

### Frontend
- Landing page with hero, URL input, recent reports, stats
- Auth page with Firebase email/password login/signup
- Report generation page with SSE streaming + blinking cursor
- Report view page with **Mermaid diagram rendering** (dark-themed), TOC sidebar, share/regenerate/edit
- Browse/search reports page with pagination
- User dashboard with credit balance, reports list, **payment + credit transaction history**
- Credits page with 3 pricing tiers + Stripe checkout (**fixed: polledRef prevents double-polling, URL cleared after success**)
- Report editor with markdown textarea + live preview
- Beautiful dark theme with custom Mermaid styles

## Prioritized Backlog
### P0 (Critical)
- [x] Core report generation flow
- [x] Firebase authentication
- [x] Credit system
- [x] Stripe payments
- [x] SSE streaming

### P1 (Important)
- [ ] GitHub token support for private repos (Phase 2)
- [ ] Custom LLM key configuration with fallback models
- [ ] Content safety/malware detection
- [ ] User API key management page

### P2 (Nice to Have)
- [ ] Report sharing with social media previews
- [ ] Report comparison (before/after regeneration)
- [ ] Batch report generation
- [ ] Report templates/customization
- [ ] Community voting/rating on reports
- [ ] SEO optimization for report pages

## Next Tasks
1. Add custom API key configuration (user can bring their own Claude/OpenAI key)
2. Add fallback model support (if Claude fails, try GPT)
3. Private repo support with GitHub token
4. Content safety checks
5. Report SEO and social sharing metadata
