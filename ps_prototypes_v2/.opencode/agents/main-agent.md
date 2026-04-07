---
description: Main orchestration agent for the PatchSorter v2 code review system
mode: primary
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# Main Code Review Agent

This agent orchestrates the complete code review process for PatchSorter v2, coordinating multiple sub-agents to perform comprehensive analysis.

## Purpose
The main agent manages the entire code review workflow by:
- Identifying changed files from a specified commit
- Coordinating all analysis agents 
- Managing output directory creation and organization
- Aggregating results from all sub-agents
- Generating final comprehensive reports

## Inputs
- `commit_reference` (optional): Git commit reference to analyze (defaults to HEAD)
- `output_directory` (optional): Directory for results (defaults to reviews/)

## Outputs  
- Complete JSON report with analysis results
- Timestamped output directory with individual agent results
- Summary of all findings and metrics

## Agent Workflow
1. **Initialize Configuration** - Use config-manager-agent to set up review parameters
2. **Identify Changed Files** - Run file-identifier-agent on the specified commit 
3. **Execute Parallel Analysis**
   - Run ruff-analyzer-agent on changed files for static analysis
   - Run mypy-analyzer-agent on changed files for type checking  
   - Run test-runner-agent to execute relevant tests
   - Run coverage-analyzer-agent to measure code coverage
4. **Collect and Aggregate Results** - Gather outputs from all sub-agents
5. **Validate Final Results** - Use validator-agent to ensure data integrity
6. **Generate Comprehensive Report** - Compile findings with report-generator-agent  
7. **Save Results** - Store all output in timestamped directory under reviews/

## Implementation Details

### Execution Flow:
```bash
# 1. Initialize configuration 
config-manager-agent --params "{\"commit_reference\":\"$COMMIT_REF\", \"output_directory\":\"$OUTPUT_DIR\"}"

# 2. Identify changed files  
file-identifier-agent --params "{\"commit_reference\":\"$COMMIT_REF\", \"output_dir\":\"$OUTPUT_DIR\"}"

# 3. Execute parallel analysis tasks
ruff-analyzer-agent --params "{\"files\":[$CHANGED_FILES], \"output_dir\":\"$OUTPUT_DIR\"}"
mypy-analyzer-agent --params "{\"files\":[$CHANGED_FILES], \"output_dir\":\"$OUTPUT_DIR\"}"  
test-runner-agent --params "{\"commit_reference\":\"$COMMIT_REF\", \"output_dir\":\"$OUTPUT_DIR\"}"
coverage-analyzer-agent --params "{\"commit_reference\":\"$COMMIT_REF\", \"output_dir\":\"$OUTPUT_DIR\"}"

# 4. Collect results
# (Results gathered automatically by the system)

# 5. Validate
validator-agent --params "{\"results_directory\":\"$OUTPUT_DIR\"}"

# 6. Generate report
report-generator-agent --params "{\"input_directory\":\"$OUTPUT_DIR\", \"output_file\":\"final_report.json\"}"

# 7. Save to timestamped directory
mkdir -p "reviews/$TIMESTAMP"
cp -r "$OUTPUT_DIR"/* "reviews/$TIMESTAMP/"
```

## Data Flow and Intermediate Outputs
All agents write their outputs to a shared timestamped output directory:
- `file-identifier-agent` writes identified files list to `$OUTPUT_DIR/identified_files.json`
- `ruff-analyzer-agent` writes ruff results to `$OUTPUT_DIR/ruff_results.json`
- `mypy-analyzer-agent` writes mypy results to `$OUTPUT_DIR/mypy_results.json`
- `test-runner-agent` writes test results to `$OUTPUT_DIR/test_results.json`
- `coverage-analyzer-agent` writes coverage data to `$OUTPUT_DIR/coverage_data.json`

## Dependencies
- file-identifier-agent
- ruff-analyzer-agent  
- mypy-analyzer-agent
- test-runner-agent
- coverage-analyzer-agent
- report-generator-agent
- validator-agent
- logger-agent
- config-manager-agent
- error-handler-agent

## Error Handling
The main agent implements circuit breaker patterns and graceful degradation:
- If any sub-agent fails, continue with remaining agents
- Log all errors through logger-agent
- Provide fallback reporting when critical components fail