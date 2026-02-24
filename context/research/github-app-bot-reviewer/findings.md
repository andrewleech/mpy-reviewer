---
timestamp: 2026-02-24T00:00:00Z
research_topic: "Can a GitHub App bot user be added as a requested reviewer on a pull request?"
---

# GitHub App Bot User as PR Reviewer -- Research Findings

## 1. Can GitHub App bot users appear in the PR reviewer dropdown in the GitHub UI?

**No.** GitHub App bot users (e.g., `my-app[bot]`) do not appear in the reviewer
dropdown in the GitHub UI. The dropdown is populated from repository collaborators
and organization members. GitHub App bot accounts are a distinct account type
(`type: "Bot"`) created by GitHub Apps, not regular user accounts. They cannot be
added as repository collaborators and therefore do not appear in the reviewer
suggestion UI.

Sources:
- https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/requesting-a-pull-request-review
- https://github.com/orgs/community/discussions/65546

## 2. Can you programmatically request a review from a bot user via the GitHub API?

**No.** The `POST /repos/{owner}/{repo}/pulls/{pull_number}/requested_reviewers`
endpoint accepts a `reviewers` array of user logins. However, requesting a review
from a bot account will fail with a **422 Unprocessable Entity** error:

> "Reviews may only be requested from collaborators. One or more of the users or
> teams you specified is not a collaborator of the repository."

This was confirmed by the Jetpack project (issue #37058) where including a bot
account like `renovate-approve[bot]` in a reviewer list caused the entire API call
to fail, preventing even the human reviewers in the same request from being assigned.

The fix implemented was to filter out `[bot]` accounts before making the API call.

Sources:
- https://github.com/Automattic/jetpack/issues/37058
- https://docs.github.com/en/rest/pulls/review-requests

## 3. Limitations and permissions

### Bot accounts are not collaborators
GitHub App bot accounts (`type: "Bot"`) are fundamentally different from user
accounts (`type: "User"`). They:
- Are created automatically when a GitHub App is installed
- Cannot be added as repository collaborators
- Cannot appear in CODEOWNERS files
- Have a restricted set of capabilities (cannot create/delete repos, etc.)
- Cannot be targeted by review requests

### Machine user accounts (workaround)
Some organizations use "machine user" accounts -- regular `type: "User"` accounts
operated by automation (e.g., `k8s-ci-robot`). These CAN be added as collaborators
and CAN be requested as reviewers, but they consume a seat in the organization and
are a separate concept from GitHub App bot users.

### GitHub Apps CAN submit reviews
While bot users cannot be *requested* as reviewers, GitHub Apps CAN submit reviews
on PRs via `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`. The review
appears as authored by the app's bot user. This is the standard pattern used by
review bots (ChatGPT-CodeReview, ansys/review-bot, etc.).

### Team review requests from Apps have additional bugs
GitHub Apps also cannot request reviews from *teams* via the API, getting a 422
error: "Could not resolve to a node with the global id of [team-id]". This is a
separate known issue.

Sources:
- https://github.com/orgs/community/discussions/66049
- https://github.com/orgs/community/discussions/65546
- https://github.com/orgs/community/discussions/63129

## 4. Alternative approaches

### A. Listen for other PR events instead of `review_requested`
Since the bot cannot be requested as a reviewer, use alternative triggers:
- `pull_request.opened` / `pull_request.synchronize` -- trigger on PR creation/update
- `pull_request.labeled` -- trigger when a specific label (e.g., "bot-review") is added
- `issue_comment.created` -- trigger on a slash command comment (e.g., "/review")
- `pull_request.ready_for_review` -- trigger when draft is marked ready

### B. Submit reviews proactively (the standard pattern)
Most review bots do NOT wait to be requested. They subscribe to `pull_request`
webhook events and proactively submit reviews via the Reviews API. The bot's review
appears in the PR timeline as `my-app[bot] reviewed`.

### C. Use a machine user account
Create a regular GitHub user account for the bot, add it as a collaborator, and
request reviews from it. The machine user can then trigger the actual bot logic.
Downside: consumes an org seat.

### D. Use GitHub Actions with `review_requested` on a human proxy
Add a human or machine user to the reviewer list, then have a GitHub Action
triggered by `pull_request.review_requested` check if the requested reviewer
matches a designated "proxy" account and dispatch the bot's review logic.

### E. Use `repository_dispatch` or `workflow_dispatch`
Trigger bot review via an API call to `repository_dispatch` from external tooling
or another workflow.

## Key Distinction

- **Requesting a review FROM a bot** (adding bot to reviewer list): NOT POSSIBLE
- **Bot SUBMITTING a review** (bot posts a review on a PR): FULLY SUPPORTED

The GitHub review system treats "requesting" and "submitting" as separate
operations with different permission models.
