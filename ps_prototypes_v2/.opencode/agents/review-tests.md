---
description: Runs pytest with coverage and returns structured results. Invoked by the review orchestrator — do not call directly.
mode: subagent
temperature: 0.0
tools:
  bash: true
  write: true
  edit: false
---

# review-tests

You run the test suite and return structured results. You do not write reports or make code changes.

## Steps

# Use timestamp from first argument if provided, otherwise generate new one:
if [ -n "$1" ]; then
  TIMESTAMP="$1"
else
  TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
fi

Create temporary directory for this execution in ./tmp/review_cache/${TIMESTAMP}/test_results/

Run the following commands exactly and capture all output.

```bash
python3 -m pytest tests/ -v --tb=short 2>&1
```

```bash
python3 -m pytest --cov=src --cov-report=term-missing 2>&1
```

## Output

Create temporary files for test results:
- ./tmp/review_cache/${TIMESTAMP}/test_results/test_run_output.txt
- ./tmp/review_cache/${TIMESTAMP}/test_results/coverage_output.txt

Return a single markdown block structured as follows:

```markdown
### Test Run
**Passed / Failed / Errors:** X / Y / Z

File: ./tmp/review_cache/${TIMESTAMP}/test_results/test_run_output.txt

### Coverage
File: ./tmp/review_cache/${TIMESTAMP}/test_results/coverage_output.txt
```

Flag any test failure with `❌` and any module below 80% coverage with `⚠️`.
If pytest is not installed, report: `⚠️ pytest not found — install with pip install pytest pytest-cov`.
