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
Establishes the specific ruff linting rules that should be applied to code review process with clear rationale and thresholds.

## Rules and Standards
- Enforce PEP 8 compliance with project-specific extensions  
- Define severity levels (error, warning, info) with clear definitions for each level:
  - Error: Code that will definitely cause runtime issues or violates strict coding standards
  - Warning: Potential issues that may affect code quality or maintainability 
  - Info: Style suggestions that don't impact functionality but improve readability
- Specify which ruff rules are enabled/disabled based on project requirements with documented rationale
- Set threshold values for issue counts per file with clear escalation procedures
- Enforce consistent line length and indentation standards across all Python files

## Integration Points
- Used by ruff-analyzer-agent for linting enforcement  
- Connected to main-agent for result interpretation
- Provides rule definitions to validation processes
- Integrated with mypy type checking for comprehensive code quality assessment

## Parameters
- `enable_rules` (array): List of ruff rules to enable with specific documentation on each rule's purpose
- `disable_rules` (array): List of ruff rules to disable with detailed rationale and alternatives considered  
- `max_issues_per_file` (integer): Maximum allowed issues per file before triggering warning/error status
- `severity_threshold` (string): Minimum severity level to report ('error', 'warning', or 'info')
- `line_length_limit` (integer): Maximum line length for code formatting enforcement
- `exclude_patterns` (array): File patterns to exclude from linting analysis

## Ruff Configuration Examples
```toml
# Standard PEP 8 compliance with project extensions and performance considerations
select = ["E", "W", "F", "C9", "B", "A"]
extend-ignore = ["E501"]  # Allow long lines in certain cases for readability
max-line-length = 88
fix = true
force-exclude = true

# Project-specific rule configurations
[tool.ruff]
line-length = 88
target-version = "py38"
```

## Rule Selection Guidelines
- Enable: E (Error), W (Warning) - Core Python errors and style issues  
- Disable: E501, F401, F403 - Specific rules that may conflict with project needs or are too strict
- Severity mapping:
  - Error level: E722, E999, F821 (hard runtime issues)
  - Warning level: E711, E712, W505 (style and maintainability concerns)  
  - Info level: C901, B006 (code structure suggestions)

## Performance Considerations
- Configure appropriate timeout values to prevent hanging on large files
- Set reasonable issue thresholds to avoid overwhelming developers with too many minor issues
- Enable automatic fixing where appropriate to reduce manual intervention

## Script Integration
This skill's functionality is implemented by the script at `.opencode/skills/ruff-linting-skill/scripts/ruff_runner.py` which provides the actual execution logic for running ruff analysis.