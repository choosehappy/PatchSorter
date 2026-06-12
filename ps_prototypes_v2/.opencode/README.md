# Opencode Code Review Agent System

This document provides an overview of the complete opencode agent system for code review.

## System Overview

The code review agent system is designed to provide comprehensive analysis of code changes in PatchSorter v2 using a granular, modular approach with enhanced robustness features.

## Architecture Components

### Agents (Located in .opencode/agents/)
1. **main-agent.md** - Main orchestrator
2. **file-identifier-agent.md** - Identifies changed files  
3. **config-manager-agent.md** - Manages configurations
4. **ruff-analyzer-agent.md** - Ruff static analysis
5. **mypy-analyzer-agent.md** - Mypy type checking
6. **test-runner-agent.md** - Test execution
7. **coverage-analyzer-agent.md** - Coverage measurement
8. **report-generator-agent.md** - Report compilation
9. **validator-agent.md** - Input/output validation
10. **logger-agent.md** - Logging and monitoring  
11. **error-handler-agent.md** - Error management

### Skills (Located in .opencode/skills/)
1. **file-identification-skill/** - File change detection rules
2. **config-management-skill/** - Configuration handling standards
3. **ruff-linting-skill/** - Ruff-specific linting rules
4. **mypy-type-checking-skill/** - Mypy type checking requirements
5. **pytest-execution-skill/** - Test framework usage
6. **coverage-analysis-skill/** - Coverage analysis standards  
7. **output-formatting-skill/** - Report formatting conventions
8. **security-validation-skill/** - Security validation rules

## Key Features

### Granular Design
- Each agent has a specific, well-defined responsibility
- Fine-grained separation of concerns for maintainability
- Modular approach allows independent updates and testing

### Robustness Enhancements  
- Circuit breaker patterns to prevent cascading failures
- Comprehensive error handling with graceful degradation
- Input validation and security measures
- Performance monitoring and logging capabilities
- Retry mechanisms with exponential backoff

### Integration Points
All agents communicate through standardized interfaces defined in the skills.
The system uses a hierarchical configuration approach where each agent can access validated configurations.

## Usage Pattern

1. User invokes main-agent with commit reference parameter
2. Main agent coordinates all sub-agents through proper workflows
3. Each agent performs its specific function using skill definitions 
4. Results are aggregated and formatted into final reports
5. Reports saved to timestamped directory in reviews/

## Directory Structure
```
.opencode/
├── package.json          # Dependencies
├── .gitignore            # Git ignore rules
├── agents/               # All agent implementations  
│   ├── main-agent.md
│   ├── file-identifier-agent.md
│   └── ... (all other agents)
├── skills/               # Skill definitions
│   ├── file-identification-skill/
│   │   └── SKILL.md
│   └── ... (all other skills)
└── README.md             # This documentation
```

## Implementation Benefits

This enhanced approach provides:
- Production-ready error handling and security measures
- Clear separation of concerns with well-defined interfaces  
- Configurable parameters for different environments
- Comprehensive monitoring and logging capabilities
- Resilient design that continues to function even when individual components fail
- Scalable architecture that can be extended with additional agents or skills

## Running the Code Review System

To run a code review:
```bash
# Run review on HEAD
.opencode/run-review.sh

# Run review for specific commit  
.opencode/run-review.sh <commit-hash>
```