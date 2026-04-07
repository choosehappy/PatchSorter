---
description: Identifies changed files from git commit references
mode: subagent
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# File Identifier Agent

This agent identifies changed files from a specified git commit reference.

## Purpose
Detects which files have been modified between commits to limit analysis scope and improve performance.

## Inputs
- `commit_reference` (required): Git commit reference to compare against
- `base_commit` (optional): Base commit for comparison (defaults to HEAD~1)
- `output_dir` (required): Directory to save intermediate outputs

## Outputs
- List of changed file paths in JSON format at `$OUTPUT_DIR/identified_files.json`
- File count statistics  
- Validation results
- Intermediate data for other agents

## Functionality
1. Execute git diff command to identify changes
2. Validate file paths are within repository bounds
3. Filter out non-code files if needed
4. Save identified files list as JSON for reuse by other agents
5. Return clean list of modified files for analysis

## Integration Points
- Connected to main-agent for change detection
- Provides input to all analyzer agents through `$OUTPUT_DIR/identified_files.json`
- Validates commit references through security-validation-skill
- Other agents can read the identified file list directly from output directory

## Error Handling
- Handles invalid commit references gracefully
- Manages permission errors when accessing repository
- Returns empty list on git command failures
- Saves partial results to output directory even if processing fails