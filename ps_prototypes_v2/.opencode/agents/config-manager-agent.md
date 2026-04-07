---
description: Manages configuration for the code review process  
mode: subagent
temperature: 0.0
tools:
  write: true
  edit: false
  bash: true
---
# Config Manager Agent

This agent manages configuration for the code review process.

## Purpose
Sets up and coordinates all configuration parameters needed across different agents in the review process.

## Inputs
- `commit_reference` (required): Git commit reference to analyze  
- `output_dir` (required): Base directory where results should be stored
- `review_config` (optional): User-defined configuration options

## Outputs
- Configuration data for all other agents
- Output path structure specification 
- Validation of input parameters

## Functionality
1. Parse git commit reference or repository state  
2. Create timestamped output directory under `$OUTPUT_DIR`
3. Generate configuration parameters for each sub-agent
4. Validate all inputs and create necessary directories
5. Provide structured config data to other agents

## Integration Points
- Connected to main-agent for orchestration
- Provides config data to all other agents in the review process  
- Uses config-management-skill for configuration standards
- Creates output directory structure for all agents

## Error Handling
- Handles invalid commit references gracefully
- Ensures required directories are created
- Returns error status on configuration failures