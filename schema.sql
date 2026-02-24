-- MicroPython Review Database Schema

-- Pull requests
CREATE TABLE IF NOT EXISTS prs (
    id INTEGER PRIMARY KEY,
    number INTEGER UNIQUE NOT NULL,
    title TEXT,
    body TEXT,
    author TEXT,
    state TEXT,
    created_at TEXT,
    merged_at TEXT,
    closed_at TEXT,
    changed_files INTEGER,
    commits INTEGER,
    additions INTEGER,
    deletions INTEGER,
    base_branch TEXT
);

-- Inline review comments (on specific code lines)
CREATE TABLE IF NOT EXISTS review_comments (
    id INTEGER PRIMARY KEY,
    pr_number INTEGER NOT NULL,
    body TEXT,
    path TEXT,
    line INTEGER,
    original_line INTEGER,
    diff_hunk TEXT,
    created_at TEXT,
    updated_at TEXT,
    in_reply_to_id INTEGER,
    commit_id TEXT,
    FOREIGN KEY (pr_number) REFERENCES prs(number)
);

-- General PR discussion comments
CREATE TABLE IF NOT EXISTS issue_comments (
    id INTEGER PRIMARY KEY,
    pr_number INTEGER NOT NULL,
    body TEXT,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY (pr_number) REFERENCES prs(number)
);

-- Review verdicts (APPROVED, CHANGES_REQUESTED, etc)
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    pr_number INTEGER NOT NULL,
    state TEXT,
    body TEXT,
    created_at TEXT,
    commit_id TEXT,
    FOREIGN KEY (pr_number) REFERENCES prs(number)
);

-- Sync state for incremental updates
CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Domain taxonomy
CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

-- Themes within domains
CREATE TABLE IF NOT EXISTS themes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER,
    name TEXT NOT NULL,
    description TEXT,
    example_comment_id INTEGER,
    FOREIGN KEY (domain_id) REFERENCES domains(id)
);

-- Comment categorization (13-field enhanced schema)
CREATE TABLE IF NOT EXISTS comment_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER NOT NULL,
    comment_type TEXT NOT NULL,  -- 'review_comment', 'issue_comment', 'review'
    domain_id INTEGER,
    theme TEXT,  -- freeform description of the specific issue/pattern
    severity TEXT,  -- 'blocking', 'suggestion', 'nitpick'
    is_style_example INTEGER DEFAULT 0,
    categorized_at TEXT,
    -- Enhanced categorization fields
    component TEXT,          -- py_core, extmod, port_specific, drivers, tools, tests, docs, build_system, examples
    port TEXT,               -- esp32, stm32, rp2, unix, etc. (NULL for generic)
    subsystem TEXT,          -- bluetooth, usb, uart, gc, vm, etc. (NULL if not applicable)
    language_context TEXT,   -- c_code, python_code, documentation, makefile, cmake, shell_script, yaml
    code_construct TEXT,     -- function, macro, struct, typedef, class, module, test_case, etc.
    concern_type TEXT,       -- correctness, safety, api_design, style, performance, portability, etc.
    feedback_type TEXT,      -- question, suggestion, requirement, information, praise, merge
    is_pattern INTEGER DEFAULT 0,
    cpython_related INTEGER DEFAULT 0,
    has_code_suggestion INTEGER DEFAULT 0,
    keywords TEXT,           -- JSON array of 2-5 technical terms
    UNIQUE(comment_id, comment_type),
    FOREIGN KEY (domain_id) REFERENCES domains(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_review_comments_pr ON review_comments(pr_number);
CREATE INDEX IF NOT EXISTS idx_review_comments_path ON review_comments(path);
CREATE INDEX IF NOT EXISTS idx_issue_comments_pr ON issue_comments(pr_number);
CREATE INDEX IF NOT EXISTS idx_reviews_pr ON reviews(pr_number);
CREATE INDEX IF NOT EXISTS idx_comment_categories_domain ON comment_categories(domain_id);
CREATE INDEX IF NOT EXISTS idx_comment_categories_severity ON comment_categories(severity);
CREATE INDEX IF NOT EXISTS idx_comment_categories_component ON comment_categories(component);
CREATE INDEX IF NOT EXISTS idx_comment_categories_language ON comment_categories(language_context);
CREATE INDEX IF NOT EXISTS idx_prs_created ON prs(created_at);

-- Insert default domains
INSERT OR IGNORE INTO domains (name, description) VALUES
    ('code_style', 'Formatting, naming conventions, code structure'),
    ('memory', 'Allocation, garbage collection, buffer handling'),
    ('error_handling', 'Return value checks, exception handling'),
    ('api_design', 'Function signatures, module structure, public interfaces'),
    ('performance', 'Optimization, efficiency concerns'),
    ('portability', 'Cross-platform compatibility, hardware abstraction'),
    ('documentation', 'Comments, docstrings, README updates'),
    ('testing', 'Test coverage, test quality, test patterns'),
    ('security', 'Input validation, bounds checking, safety'),
    ('architecture', 'Design patterns, module organization, dependencies'),
    ('build_system', 'Makefiles, configuration, compilation'),
    ('correctness', 'Logic errors, edge cases, spec compliance');
