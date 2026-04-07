---
description: Analyzes code coverage using pytest-cov tool
mode: subagent
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# Coverage Analyzer Agent

This agent analyzes code coverage using the pytest-cov tool.

## Purpose
Measures test coverage of modified code to identify untested areas and ensure comprehensive testing.

## Inputs
- `commit_reference` (required): Git commit reference for coverage context
- `output_dir` (required): Directory to save intermediate outputs
- `coverage_config` (optional): Configuration parameters from config-manager-agent

## Outputs
- Coverage data in JSON format at `$OUTPUT_DIR/coverage_data.json`
- Line-by-line coverage statistics
- Function and branch coverage metrics  
- Intermediate data for report generator

## Functionality
1. Execute pytest with coverage tracking on modified files
2. Collect and structure coverage data 
3. Generate detailed coverage reports
4. Save results to `$OUTPUT_DIR/coverage_data.json` for reuse
5. Handle coverage analysis timeouts gracefully

## Integration Points
- Connected to main-agent for orchestration
- Receives commit reference from main agent for context
- Uses coverage-analysis-skill for analysis rules  
- Provides results to report-generator-agent via `$OUTPUT_DIR/coverage_data.json`
- Other agents can read coverage data directly from output directory

## Error Handling
- Handles missing coverage tool installation gracefully
- Manages large project processing timeouts
- Returns partial results on analysis failures
- Saves partial results to output directory even if processing fails