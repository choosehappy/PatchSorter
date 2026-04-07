---
name: ruff-linting
description: Define ruff-specific linting rules and standards for PatchSorter v2
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# Ruff Linting Skill

This skill defines ruff-specific linting rules and standards for PatchSorter v2.

## Purpose
Establishes the specific ruff linting rules that should be applied to code review process.

## Rules and Standards
- Enforce PEP 8 compliance with project-specific extensions  
- Define severity levels (error, warning, info) for different rule violations
- Specify which ruff rules are enabled/disabled for this project
- Set threshold values for issue counts per file

## Integration Points
- Used by ruff-analyzer-agent for linting enforcement  
- Connected to main-agent for result interpretation
- Provides rule definitions to validation processes

## Parameters
- `enable_rules` (array): List of ruff rules to enable
- `disable_rules` (array): List of ruff rules to disable 
- `max_issues_per_file` (integer): Maximum allowed issues per file
- `severity_threshold` (string): Minimum severity level to report

## Ruff Configuration Examples
```
# Standard PEP 8 compliance with project extensions
select = ["E", "W", "F", "C9", "B", "A"]
extend-ignore = ["E501"]  # Allow long lines in certain cases
max-line-length = 88
```