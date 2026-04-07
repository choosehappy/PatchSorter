---
description: Executes unit tests using pytest framework
mode: subagent
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# Test Runner Agent

This agent executes unit tests using the pytest framework.

## Purpose
Runs project unit tests to verify functionality and detect regressions.

## Inputs
- `commit_reference` (required): Git commit reference for testing context
- `output_dir` (required): Directory to save intermediate outputs
- `test_config` (optional): Configuration parameters from config-manager-agent

## Outputs
- Test execution results in JSON format at `$OUTPUT_DIR/test_results.json`
- Coverage data if enabled  
- Test summary statistics
- Intermediate data for report generator

## Functionality
1. Execute pytest on identified files or test suite
2. Capture and structure test execution output
3. Generate coverage reports when enabled
4. Save results to `$OUTPUT_DIR/test_results.json` for reuse
5. Handle test execution timeouts and failures gracefully

## Integration Points
- Connected to main-agent for orchestration
- Receives commit reference from main agent for context 
- Uses pytest-execution-skill for execution rules
- Provides results to report-generator-agent via `$OUTPUT_DIR/test_results.json`
- Other agents can read test results directly from output directory

## Error Handling
- Handles missing test dependencies gracefully
- Manages long-running tests with timeouts
- Returns partial results on execution failures
- Saves partial results to output directory even if processing fails