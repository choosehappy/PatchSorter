---
name: pytest-execution
description: Define pytest framework usage and execution rules for PatchSorter v2
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# Pytest Execution Skill

This skill defines pytest framework usage and execution rules for PatchSorter v2.

## Purpose
Establishes the specific pytest execution standards that should be applied to code review process.

## Rules and Standards
- Define test execution parameters and timeouts  
- Specify which tests should be run (all, changed files only)
- Set resource limits for test execution
- Define success/failure criteria for test runs

## Integration Points
- Used by test-runner-agent for test execution  
- Connected to main-agent for result interpretation
- Provides framework rules to validation processes

## Parameters
- `test_timeout_seconds` (integer): Maximum seconds allowed per test run
- `max_test_workers` (integer): Maximum concurrent test workers
- `enable_coverage` (boolean): Whether to collect coverage data
- `fail_on_warnings` (boolean): Treat warnings as failures  

## Pytest Configuration Examples
```
# Standard pytest configuration with project-specific settings  
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"] 
python_functions = ["test_*"]
addopts = "--verbose --tb=short"
timeout = 30
```