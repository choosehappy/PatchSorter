---
name: file-identification
description: Identify changed files in a git repository for code review processes
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# File Identification Skill

This skill defines the rules and methods for identifying changed files in a git repository.

## Purpose
Establishes standardized approaches for detecting which files have been modified between commits.

## Rules and Standards
- Only consider files within the repository bounds
- Filter out non-code files (config, documentation) if needed  
- Handle symbolic links properly
- Support various git commit reference formats

## Validation Requirements
- Verify commit references exist in repository
- Check file paths don't escape repository boundaries
- Ensure proper permissions for accessing files
- Validate that identified files are readable2

## Integration Points
- Used by file-identifier-agent for change detection  
- Connected to security-validation-skill for input validation
- Provides data to all analyzer agents for scope limiting

## Parameters
- `include_non_code_files` (boolean): Whether to include config/documentation files
- `max_file_count` (integer): Maximum number of files to process in one run
- `base_commit` (string): Default base commit reference when not specified