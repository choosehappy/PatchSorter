---
name: review-scope
description: Determines which files are in scope for a review run
license: MIT
compatibility: opencode
metadata:
  audience: reviewers
  workflow: code-review
---

# Skill: review-scope

Determines which files are in scope for a review run.

## Inputs

The user can pass any of the following to specify what files to review:
- `all` — every `.py` file under `src/` and `tests/`
- `changes` — only files modified since the last commit (default if nothing specified)
- A specific commit SHA — files changed in that commit
- A branch name or reference — files changed compared to that branch
- A range of commits — files changed between two commits/tags
- File paths — specific files or directories to review
- Pull Request number — files changed in that PR (GitHub only)

## Commands

```bash
# scope == "changes"
git diff --name-only HEAD

# scope == "all" 
find src/ tests/ -name "*.py" | grep -v __pycache__ | grep -v old | sort

# For a specific commit SHA
git show --name-only <commit_sha>

# For branch comparison
git diff --name-only <branch_name> HEAD

# For range of commits
git diff --name-only <start_commit>..<end_commit>

# For file paths (if provided directly)
echo "<file_path_1>
<file_path_2>" | grep -E "\.(py)$"
```

## Output

Return a plain list of file paths, one per line. This list is passed to downstream subagents.
If the list is empty, write `No files in scope. Nothing to review.` and stop.

## Processing Logic

1. If user specifies "all", return all Python files under src/ and tests/
2. If user specifies "changes" or nothing, return files modified since last commit
3. If user provides a commit SHA, return files changed in that specific commit
4. If user provides a branch name, return files changed compared to that branch
5. If user provides a range (e.g., "HEAD~5..HEAD"), return files changed in that range
6. If user provides file paths directly, validate and return those Python files with proper absolute path resolution
7. If user references PR numbers or tags/releases, determine the appropriate git command for that context

## Path Resolution

When processing file paths:
- All returned file paths should be absolute paths to ensure tools can locate them correctly
- When validating file paths directly provided by users, resolve relative paths against the repository root (current working directory)
- Ensure all files exist before returning them in the scope list
- Repository root is determined dynamically as the current working directory when this skill is invoked

## Confirmation Process

After determining the files to review:
1. Present the list of files to the user
2. Ask: "Are these the files you want reviewed? (y/n)"
3. If user confirms with "y", proceed with the review scope
4. If user declines with "n", ask for clarification on what they'd like instead
5. Repeat until user confirms or provides a different specification

## Example Interaction Flow

User: "Review changes from commit abc123"
System: "I found these files changed in commit abc123:
- src/module1.py
- tests/test_module1.py
Are these the files you want reviewed? (y/n)"

User: "No, I want to review all files"
System: "I'll review all Python files under src/ and tests/"
