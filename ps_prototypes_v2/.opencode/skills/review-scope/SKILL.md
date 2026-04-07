# Skill: review-scope

Determines which files are in scope for a review run.

## Inputs

The user passes one of:
- `all` — every `.py` file under `src/` and `tests/`
- `changes` — only files modified since the last commit
- _(nothing)_ — default to `changes`; note the assumption in the report

## Commands

```bash
# scope == "changes"
git diff --name-only HEAD

# scope == "all"
find src/ tests/ -name "*.py" | grep -v __pycache__ | grep -v old | sort
```

## Output

Return a plain list of file paths, one per line. This list is passed to downstream subagents.
If the list is empty, write `No files in scope. Nothing to review.` and stop.
