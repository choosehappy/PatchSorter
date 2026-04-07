---
name: mypy-type-checking
description: Define mypy-specific type checking rules and standards for PatchSorter v2
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# Mypy Type Checking Skill

This skill defines mypy-specific type checking rules and standards for PatchSorter v2.

## Purpose
Establishes the specific mypy type checking requirements that should be applied to code review process.

## Rules and Standards
- Enforce strict type checking with project-specific allowances  
- Define severity levels (error, warning) for different type issues
- Specify which mypy checks are enabled/disabled for this project
- Set threshold values for type errors per file

## Integration Points
- Used by mypy-analyzer-agent for type validation  
- Connected to main-agent for result interpretation
- Provides checking rules to validation processes

## Parameters
- `strict_mode` (boolean): Enable strict type checking mode
- `enable_plugins` (array): List of mypy plugins to enable
- `disable_error_codes` (array): Error codes to ignore 
- `max_errors_per_file` (integer): Maximum allowed errors per file

## Mypy Configuration Examples
```
# Strict type checking with project-specific allowances
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
```