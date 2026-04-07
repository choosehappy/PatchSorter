# Skill: review-report-format

Defines the canonical output format for all review reports.

## File Location

```bash
mkdir -p review
DATETIME=$(date +"%Y%m%d_%H%M%S")
# write to: review/${DATETIME}.md
```

## Template

```markdown
# Code Review — {DATETIME}

**Scope:** `all | changes`
**Files reviewed:** {N}
**Reviewer:** PatchSorter Review Agent

---

## Summary

One paragraph: overall health, most critical issues, merge readiness.

---

## Static Analysis

### Ruff
{findings | "✅ No violations"}

### Ruff Format
{findings | "✅ No formatting issues"}

### Mypy
{findings | "✅ No type errors"}

---

## Test Results

**Passed / Failed / Errors:** X / Y / Z
**Coverage:**

| Module | Coverage |
|--------|----------|
| ...    | ...%     |

{findings | "✅ All tests pass. Coverage ≥80% across all modules."}

---

## Findings

{repeat per finding:}

### [{SEVERITY}] {Short title}
**File:** `path/to/file.py` **Line:** N
**Category:** Correctness | Compliance | Domain | Scalability | Tests | Documentation
**Detail:** One sentence — what is wrong and why it matters.
**Suggestion:** One sentence — concrete, actionable fix.

---

Severity levels: `CRITICAL` · `HIGH` · `MEDIUM` · `LOW` · `INFO`

---

## Scalability & Efficiency Highlights

All scalability findings ordered by expected impact at ≥1B objects.

---

## Missing Tests

| Module | Missing scenario |
|--------|-----------------|
| ...    | ...             |

---

## AGENTS.md Compliance Checklist

{paste completed checklist from review-compliance-checklist skill}

---

## Recommended Actions

Ordered by priority. Concrete tasks only — no vague suggestions.

1. ...
2. ...
```

## Rules

- Every finding must cite a file and line number.
- One clear sentence per Detail and Suggestion field.
- Do not omit any section — write "N/A" if a section has nothing to report.
- The report is the only file written. Never edit source files.
