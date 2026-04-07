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

## File Validation

After determining the file list but before saving it:
1. For each file path in the list, verify that it exists in the repository
2. If a file does not exist, attempt to find similar filenames in the current directory structure 
3. Report any files that cannot be found and suggest alternatives if possible
4. If no valid files remain after validation, exit with an error message

## Output

Return a plain list of file paths, one per line. This list is passed to downstream subagents.
If the list is empty, write `No files in scope. Nothing to review.` and stop.

## File Storage

After determining the file list, save it to:
`./tmp/review_cache/${TIMESTAMP}/scope_files.txt`

Each file path should be written as a separate line in this file for downstream processing.

## Processing Logic

1. If user specifies "all", return all Python files under src/ and tests/
2. If user specifies "changes" or nothing, return files modified since last commit
3. If user provides a commit SHA, return files changed in that specific commit
4. If user provides a branch name, return files changed compared to that branch
5. If user provides a range (e.g., "HEAD~5..HEAD"), return files changed in that range
6. If user provides file paths directly, validate and return those Python files with proper absolute path resolution
7. If user references PR numbers or tags/releases, determine the appropriate git command for that context
8. **After determining files from commit reference, verify each file exists in repository. If not found, search for similar filenames in current directory structure and suggest alternatives**
9. **For all file paths returned by this skill, ensure they exist in the repository before adding to scope list**
10. **After processing all files but before saving to scope_files.txt, validate that each file path exists**
11. **Save the final file list to ./tmp/review_cache/${TIMESTAMP}/scope_files.txt for downstream processing**

## File Validation

After determining the file list but before saving it:
1. For each file path in the list, verify that it exists in the repository
2. If a file does not exist, attempt to find similar filenames in the current directory structure 
3. Report any files that cannot be found and suggest alternatives if possible
4. If no valid files remain after validation, exit with an error message

## Implementation Example (in bash)

```bash
# After determining the initial list of files:
VALID_FILES=""
while IFS= read -r file; do
  if [ -f "$file" ]; then
    VALID_FILES="$VALID_FILES$file"$'\n'
  else
    echo "⚠️ File not found: $file (skipping)" >&2
  fi
done <<< "$INITIAL_FILE_LIST"

# If no valid files, exit early with error message
if [ -z "$VALID_FILES" ]; then
  echo "No valid files to analyze. All specified files were not found in repository." >&2
  exit 1
fi

echo "$VALID_FILES" > "./tmp/review_cache/${TIMESTAMP}/scope_files.txt"
```

## Path Resolution

When processing file paths:
- All returned file paths should be absolute paths to ensure tools can locate them correctly
- When validating file paths directly provided by users, resolve relative paths against the repository root (current working directory)
- Ensure all files exist before returning them in the scope list
- Repository root is determined dynamically as the current working directory when this skill is invoked
- **If a commit references files that don't exist in the repository, check for alternative file locations and suggest corrections**
- **For each file path processed, validate its existence and report any missing files with suggestions**

## Confirmation Process

After determining the files to review:
1. Present the list of files to the user
2. Ask: "Are these the files you want reviewed? (y/n)"
3. If user confirms with "y", proceed with the review scope
4. If user declines with "n", ask for clarification on what they'd like instead
5. Repeat until user confirms or provides a different specification
6. **If any files from commit reference don't exist in repository, notify user and suggest alternatives**
7. **For all file paths returned by this skill, ensure they exist before saving to scope_files.txt**
8. **Save the final file list to ./tmp/review_cache/${TIMESTAMP}/scope_files.txt for downstream processing**

## Example Interaction Flow

User: "Review changes from commit abc123"
System: "I found these files changed in commit abc123:
- src/module1.py
- tests/test_module1.py
Are these the files you want reviewed? (y/n)"

User: "No, I want to review all files"
System: "I'll review all Python files under src/ and tests/"
