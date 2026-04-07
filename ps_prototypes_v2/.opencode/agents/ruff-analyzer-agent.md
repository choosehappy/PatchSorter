---
description: Performs static code style checking using ruff tool
mode: subagent
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# Ruff Analyzer Agent

This agent performs static code style checking using the ruff tool.

## Purpose
Analyzes Python code for style issues, potential bugs, and adherence to coding standards.

## Inputs
- `file_list` (required): List of files to analyze
- `config` (required): Configuration parameters from config-manager-agent
- `output_dir` (required): Directory to save intermediate outputs

## Outputs
- Ruff analysis results in JSON format at `$OUTPUT_DIR/ruff_results.json`
- Severity classification of findings  
- File-level summary statistics
- Intermediate data for report generator

## Functionality
1. Execute ruff check on specified files
2. Parse and structure output data
3. Apply severity filtering based on configuration
4. Generate detailed issue reports
5. Save results to `$OUTPUT_DIR/ruff_results.json` for reuse
6. Handle tool execution timeouts

## Integration Points
- Connected to main-agent for orchestration
- Receives file list from file-identifier-agent through `$OUTPUT_DIR/identified_files.json`
- Uses ruff-linting-skill for rule definitions
- Provides results to report-generator-agent via `$OUTPUT_DIR/ruff_results.json`
- Other agents can read ruff results directly from output directory

## Error Handling
- Handles missing ruff installation gracefully
- Manages large file processing timeouts
- Returns partial results on tool failures
- Saves partial results to output directory even if processing fails