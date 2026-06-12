# Code Review Agent for PatchSorter v2

This is a multi-agent system designed specifically for code review of PatchSorter v2. It performs comprehensive analysis including static code checking, type validation, testing, and coverage assessment.

## Features

- **Multi-Agent Architecture**: Separates concerns into specialized agents (Ruff, Mypy, Tests, Coverage)
- **Clean Communication**: All sub-agents communicate through well-defined interfaces
- **Directory Management**: Automatically creates timestamped output directories
- **Standard Tool Integration**: Uses ruff, mypy, pytest, and coverage tools
- **Comprehensive Reporting**: Generates detailed JSON reports with all analysis results

## Architecture Overview

The system consists of four main components:

1. **Main CodeReviewAgent** - Orchestrates the entire review process
2. **RuffAgent** - Performs static code style checking using ruff
3. **MypyAgent** - Handles type checking using mypy 
4. **TestAgent** - Runs unit tests with pytest
5. **CoverageAgent** - Checks code coverage

## Usage

### Basic Usage
```bash
python code_review_agent.py [commit_reference]
```

If no commit reference is provided, it defaults to `HEAD`.

### Example Commands
```bash
# Review changes from current HEAD
python code_review_agent.py

# Review changes from specific commit
python code_review_agent.py abc1234

# Review changes from previous commit  
python code_review_agent.py HEAD~1
```

## Output Structure

The agent creates a timestamped directory in `reviews/` with the following structure:
```
reviews/
└── 2026-04-07_22-48-41/
    ├── final_report.json     # Complete analysis summary
    ├── ruff_analysis.json    # Ruff static analysis results  
    ├── mypy_analysis.json    # Mypy type checking results
    ├── test_results.json     # Test execution results
    └── coverage_results.json # Coverage analysis results
```

## Requirements

- Python 3.8+
- ruff (Python linter)
- mypy (Type checker)  
- pytest (Testing framework)
- torch (for PatchSorter tests)

Install dependencies:
```bash
pip install -r tests/requirements.txt
```

## How It Works

1. The agent determines which files have changed since the specified commit
2. Each sub-agent analyzes specific aspects of the codebase:
   - RuffAgent: Checks for style issues and potential bugs
   - MypyAgent: Validates type annotations  
   - TestAgent: Runs unit tests to ensure functionality
   - CoverageAgent: Verifies test coverage levels
3. All results are collected in a final report with timestamped directory structure

## Error Handling

The agent gracefully handles:
- Missing dependencies 
- Failed tests
- Analysis errors
- Module import issues (like missing torch dependency)

Each sub-agent saves its specific output to individual files, and the main agent aggregates all results into a comprehensive JSON report.

## Best Practices for Use

1. Run in repository root directory where requirements.txt is located  
2. Ensure dependencies are installed before running analysis
3. Review final_report.json for complete summary of findings
4. Check individual result files for detailed issue information