---
description: Compiles analysis results into comprehensive final reports
mode: subagent
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# Report Generator Agent

This agent compiles analysis results from all sub-agents into comprehensive final reports.

## Purpose
Aggregates findings from ruff, mypy, tests and coverage tools to produce a unified code review report.

## Inputs
- `input_directory` (required): Directory containing all intermediate outputs  
- `output_file` (required): Path for the final JSON output file
- `report_config` (optional): Configuration parameters from config-manager-agent

## Outputs
- Final comprehensive JSON report at `$OUTPUT_FILE`
- Summary of all findings and metrics
- Structured data combining results from all analysis agents

## Functionality
1. Read intermediate outputs from shared directory (`$INPUT_DIR`)
2. Parse ruff_results.json, mypy_results.json, test_results.json, coverage_data.json  
3. Aggregate findings across all tools into unified report structure
4. Generate final JSON report with comprehensive summary
5. Validate and format the complete report for consumption

## Integration Points
- Connected to main-agent for orchestration
- Reads outputs from all other agents in `$INPUT_DIR`
- Uses output-formatting-skill for report standards  
- Provides final results to main agent for saving

## Error Handling
- Handles missing intermediate files gracefully
- Maintains partial reports when some data is unavailable
- Returns error status on critical integration failures