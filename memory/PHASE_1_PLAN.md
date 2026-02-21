# Phase 1: Report Ownership & Upgrade System

## 🎯 Concept: Collaborative Report Maintenance

Instead of multiple competing reports, we have **ONE living report per repository** that can be upgraded when outdated.

## 🔄 How It Works

### Current System
```
User → Generate Report → One canonical report forever
                         (No updates, even if repo changes)
```

### New System
```
User A → Generates Report → Becomes Owner
         ↓
      30 days pass + repo gets new commits
         ↓
User B → Sees "Outdated Report - Upgrade?" → Pays 2 credits → Becomes New Owner
         ↓
      Report is regenerated with latest data
```

## 📊 Database Schema Changes

### Reports Collection (Modified)

```javascript
{
  id: "uuid",
  repo_full_name: "facebook/react",
  title: "React - A JavaScript library for building user interfaces",
  content: "...",
  
  // NEW FIELDS FOR OWNERSHIP
  current_owner_id: "user-uuid-123",
  current_owner_name: "John Doe",
  
  // NEW FIELDS FOR FRESHNESS
  generated_at: "2025-01-15T10:00:00Z",
  repo_last_commit_at: "2025-02-20T15:30:00Z",  // From GitHub API
  repo_last_commit_sha: "abc123...",
  
  // NEW FIELDS FOR VERSION HISTORY
  version: 3,
  previous_owners: [
    { user_id: "user-uuid-1", name: "Alice", generated_at: "2025-01-01" },
    { user_id: "user-uuid-2", name: "Bob", generated_at: "2025-01-15" }
  ],
  
  // EXISTING FIELDS
  repo_url: "https://github.com/facebook/react",
  language: "JavaScript",
  stars: 225000,
  // ... other metadata
}
```

## 🔧 API Changes

### Modified Endpoints

**`POST /api/reports/check`**
```javascript
// Before: Returns whether report exists
{
  exists: true,
  report: { ... }
}

// After: Returns upgrade eligibility
{
  exists: true,
  report: { ... },
  can_upgrade: true,  // NEW
  upgrade_reason: "Report is 45 days old and repo has 127 new commits",  // NEW
  days_old: 45,  // NEW
  new_commits_count: 127  // NEW
}
```

**`POST /api/reports/generate`**
```javascript
// Existing behavior PLUS:
// - Check if report exists and is upgradeable
// - If upgrading:
//   - Archive old version to previous_owners
//   - Generate new content
//   - Update owner to current user
//   - Increment version
```

### New Endpoints

**`POST /api/reports/{report_id}/upgrade`**
```javascript
// Request
POST /api/reports/abc-123/upgrade
Authorization: Bearer <token>

// Response
{
  message: "Report upgraded successfully",
  credits_remaining: 8,
  new_version: 4,
  you_are_now_owner: true
}
```

**`GET /api/reports/{report_id}/history`**
```javascript
// Response
{
  report_id: "abc-123",
  repo_name: "facebook/react",
  current_version: 4,
  history: [
    { version: 1, owner: "Alice", date: "2025-01-01", commits_analyzed: "sha1" },
    { version: 2, owner: "Bob", date: "2025-01-15", commits_analyzed: "sha2" },
    { version: 3, owner: "Charlie", date: "2025-02-01", commits_analyzed: "sha3" },
    { version: 4, owner: "You", date: "2025-02-20", commits_analyzed: "sha4" }
  ]
}
```

## 🎨 Frontend Changes

### Report View Page Updates

**Add Ownership Banner:**
```jsx
<div className="ownership-banner">
  <Avatar src={report.current_owner_avatar} />
  <div>
    <p>Maintained by <strong>{report.current_owner_name}</strong></p>
    <p className="text-sm text-muted">Version {report.version} • Updated {formatDate(report.generated_at)}</p>
  </div>
</div>
```

**Add Upgrade Alert (when outdated):**
```jsx
{canUpgrade && (
  <Alert variant="warning">
    <AlertCircle className="h-4 w-4" />
    <AlertTitle>This report is outdated</AlertTitle>
    <AlertDescription>
      Report is {daysOld} days old. The repository has {newCommits} new commits since then.
      <Button onClick={handleUpgrade} className="ml-4">
        Upgrade Report (2 credits)
      </Button>
    </AlertDescription>
  </Alert>
)}
```

**Add Version History Section:**
```jsx
<Accordion>
  <AccordionItem value="history">
    <AccordionTrigger>Version History ({report.version} versions)</AccordionTrigger>
    <AccordionContent>
      <Timeline>
        {history.map(v => (
          <TimelineItem key={v.version}>
            <strong>v{v.version}</strong> by {v.owner} on {v.date}
          </TimelineItem>
        ))}
      </Timeline>
    </AccordionContent>
  </AccordionItem>
</Accordion>
```

### Home/Browse Page Updates

**Add Upgrade Indicators:**
```jsx
<Card className={report.can_upgrade ? 'border-orange-500' : ''}>
  {report.can_upgrade && (
    <Badge variant="warning">Needs Upgrade</Badge>
  )}
  <h3>{report.repo_name}</h3>
  <p>Maintained by {report.current_owner_name}</p>
  <p className="text-xs">Last updated {daysAgo} days ago</p>
</Card>
```

## 🔍 Upgrade Eligibility Logic

```python
def is_report_upgradeable(report: dict, repo_github_data: dict) -> dict:
    """Check if report can be upgraded"""
    
    # Calculate days since last update
    report_date = datetime.fromisoformat(report["generated_at"])
    days_old = (datetime.now(timezone.utc) - report_date).days
    
    # Check if report is >30 days old
    if days_old < 30:
        return {
            "can_upgrade": False,
            "reason": "Report is still fresh (updated {days_old} days ago)"
        }
    
    # Get repo's latest commit from GitHub
    latest_commit_sha = repo_github_data["commits"][0]["sha"]
    latest_commit_date = repo_github_data["commits"][0]["date"]
    
    # Check if repo has new commits since report generation
    report_commit_sha = report.get("repo_last_commit_sha")
    if latest_commit_sha == report_commit_sha:
        return {
            "can_upgrade": False,
            "reason": "No new commits since last report"
        }
    
    # Count new commits
    new_commits = count_commits_since(report_commit_sha, latest_commit_sha)
    
    return {
        "can_upgrade": True,
        "reason": f"Report is {days_old} days old with {new_commits} new commits",
        "days_old": days_old,
        "new_commits": new_commits,
        "latest_commit_date": latest_commit_date
    }
```

## 🎮 Gamification & Reputation

### Leaderboard Ideas (Future)
- "Top Maintainers" - Users with most owned reports
- "Fresh Content Champion" - User who upgrades the most reports
- "Popular Repo Owner" - Owns reports for high-star repos

### Ownership Benefits
- Badge: "Maintains 15 reports"
- Profile shows "Owned Reports"
- Reputation points for maintaining popular repos

## 📋 Implementation Checklist

### Backend (Day 1-2)
- [ ] Update `reports` schema with new fields
- [ ] Modify `POST /api/reports/generate` to handle upgrades
- [ ] Create `POST /api/reports/{id}/upgrade` endpoint
- [ ] Create `GET /api/reports/{id}/history` endpoint
- [ ] Update `POST /api/reports/check` to return upgrade info
- [ ] Add GitHub commit comparison logic
- [ ] Add version history archival logic

### Frontend (Day 3-4)
- [ ] Update Report View page with ownership banner
- [ ] Add upgrade alert component
- [ ] Add version history accordion
- [ ] Update browse/search to show upgrade status
- [ ] Add "Upgrade Report" flow with credit confirmation
- [ ] Add success/error toasts for upgrade actions

### Testing (Day 5)
- [ ] Test upgrade flow end-to-end
- [ ] Test credit deduction for upgrades
- [ ] Test version history tracking
- [ ] Test GitHub commit comparison
- [ ] Test edge cases (no new commits, <30 days old, etc.)

### Documentation
- [ ] Update user guide with ownership concept
- [ ] Add FAQ: "How do upgrades work?"
- [ ] Add pricing page: "2 credits to own/upgrade a report"

## 🚀 Success Metrics

After Phase 1 launch, track:
- % of reports upgraded within 60 days
- Average report ownership duration
- Top maintainers (users with most owned reports)
- Credit spend on upgrades vs new reports

## 💡 Future Enhancements (Phase 1.5)

- **Auto-upgrade notifications**: Email owner when their report is outdated
- **Transfer ownership**: Current owner can transfer to another user
- **Premium reports**: Lock upgrades to original owner (paid feature)
- **Collaborative editing**: Multiple users can suggest improvements

---

**Status**: Ready for implementation  
**Estimated Time**: 5 days  
**Dependencies**: None (builds on existing codebase)
