---
name: coverage-analysis
description: Define code coverage analysis requirements and standards for PatchSorter v2
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# Coverage Analysis Skill

This skill defines code coverage analysis rules and standards for PatchSorter v2.

## Purpose
Establishes the specific coverage analysis requirements that should be applied to code review process.

## Rules and Standards
- Define minimum coverage thresholds for different file types  
- Specify which files should be included/excluded from coverage analysis
- Set reporting formats for coverage data
- Establish how coverage results are interpreted in context

## Integration Points
- Used by coverage-analyzer-agent for coverage measurement  
- Connected to main-agent for result interpretation
- Provides metrics to validation processes

## Parameters
- `minimum_coverage_percent` (float): Minimum overall coverage percentage required
- `file_coverage_thresholds` (object): Thresholds by file type
- `include_test_files` (boolean): Whether to include test files in analysis  
- `coverage_format` (string): Output format for coverage reports

## Coverage Configuration Examples
```
# Standard coverage configuration with project-specific thresholds
omit = [
    "*/tests/*",
    "*/venv/*", 
    "*/.venv/*"
]
fail_under = 80
show_missing = true
skip_covered = false
```