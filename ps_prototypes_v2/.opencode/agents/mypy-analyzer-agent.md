---
description: Performs type checking using mypy tool
mode: subagent
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# Mypy Analyzer Agent

This agent performs type checking using the mypy tool.

## Purpose
Validates Python code type annotations and identifies type-related errors.

## Inputs
- `file_list` (required): List of files to analyze  
- `config` (required): Configuration parameters from config-manager-agent
- `output_dir` (required): Directory to save intermediate outputs

## Outputs
- Mypy type checking results in JSON format at `$OUTPUT_DIR/mypy_results.json`
- Type annotation compliance metrics
- File-level error counts
- Intermediate data for report generator

## Functionality
1. Execute mypy type checking on specified files
2. Parse and structure type checking output
3. Apply severity filtering based on configuration  
4. Generate detailed error reports
5. Save results to `$OUTPUT_DIR/mypy_results.json` for reuse
6. Handle tool execution timeouts

## Integration Points
- Connected to main-agent for orchestration
- Receives file list from file-identifier-agent through `$OUTPUT_DIR/identified_files.json`
- Uses mypy-type-checking-skill for rule definitions
- Provides results to report-generator-agent via `$OUTPUT_DIR/mypy_results.json`
- Other agents can read mypy results directly from output directory

## Error Handling
- Handles missing mypy installation gracefully  
- Manages large project processing timeouts
- Returns partial results on tool failures
- Saves partial results to output directory even if processing fails