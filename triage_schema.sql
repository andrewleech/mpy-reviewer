-- Issue triage schema extensions for MicroPython Review Database

-- Issues (open and closed, excluding PRs)
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    number INTEGER NOT NULL,
    repo TEXT NOT NULL DEFAULT 'micropython/micropython',
    title TEXT,
    body TEXT,
    author TEXT,
    state TEXT,          -- open, closed
    labels TEXT,         -- JSON array of label names
    created_at TEXT,
    closed_at TEXT,
    updated_at TEXT,
    comments_count INTEGER,
    UNIQUE(repo, number)
);

-- dpgeorge's comments on issues (not PRs — PR comments are in issue_comments)
CREATE TABLE IF NOT EXISTS dpgeorge_issue_comments (
    id INTEGER PRIMARY KEY,
    issue_number INTEGER NOT NULL,
    repo TEXT NOT NULL DEFAULT 'micropython/micropython',
    body TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- Explicit issue-PR closing references from timeline events
CREATE TABLE IF NOT EXISTS issue_closing_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number INTEGER NOT NULL,
    issue_repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_repo TEXT NOT NULL,
    pr_merged INTEGER DEFAULT 0,  -- 1 if the PR was merged
    UNIQUE(issue_repo, issue_number, pr_repo, pr_number)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_issues_repo ON issues(repo);
CREATE INDEX IF NOT EXISTS idx_issues_state ON issues(state);
CREATE INDEX IF NOT EXISTS idx_issues_created ON issues(created_at);
CREATE INDEX IF NOT EXISTS idx_issues_repo_number ON issues(repo, number);
CREATE INDEX IF NOT EXISTS idx_dpgeorge_issue_comments_issue ON dpgeorge_issue_comments(issue_number, repo);
CREATE INDEX IF NOT EXISTS idx_issue_closing_refs_issue ON issue_closing_refs(issue_repo, issue_number);
CREATE INDEX IF NOT EXISTS idx_issue_closing_refs_pr ON issue_closing_refs(pr_repo, pr_number);
