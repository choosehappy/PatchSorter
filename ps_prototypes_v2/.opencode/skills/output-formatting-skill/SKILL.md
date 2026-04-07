---
name: output-formatting
description: Define report generation and output formatting standards for code review processes
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# Output Formatting Skill

This skill defines report generation and output formatting standards for the code review process.

## Purpose
Establishes standardized approaches for presenting analysis results to users.

## Rules and Standards
- Define JSON schema for all result outputs  
- Specify logging format conventions
- Establish audit trail requirements
- Set human-readable report formats

## Integration Points
- Used by report-generator-agent for output formatting
- Connected to logger-agent for log message standards  
- Provides structure definitions to validation processes

## Parameters
- `output_format` (string): Format of final results (json, markdown, html)
- `log_level` (string): Default logging level for operations
- `timestamp_format` (string): Date/time format for logs and reports
- `max_output_size` (integer): Maximum size of output files

## Output Structure Example
```json
{
  "review_metadata": {
    "commit_reference": "abc1234",
    "timestamp": "2026-04-07T10:30:00Z",
    "tool_versions": {
      "ruff": "0.1.0",
      "mypy": "1.0.0"
    }
  },
  "analysis_results": {
    "ruff_analysis": {},
    "mypy_analysis": {}, 
    "test_results": {},
    "coverage_results": {}
  },
  "summary_metrics": {
    "total_files_analyzed": 42,
    "total_issues_found": 15
  }
}
```