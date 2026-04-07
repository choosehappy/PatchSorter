---
name: config-management
description: Manage tool configurations and project-specific settings for code review processes
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# Configuration Management Skill

This skill defines how configuration is handled across the code review process.

## Purpose
Establishes standardized approaches for managing tool configurations and project-specific settings.

## Rules and Standards
- Load default configurations from repository defaults
- Allow project-specific overrides through environment variables  
- Validate all configuration parameters before use
- Support hierarchical configuration (global → project → local)

## Configuration Elements
- Tool execution timeouts and limits
- Severity thresholds for different issue types
- Analysis scope parameters (include/exclude patterns)
- Output formatting preferences

## Integration Points
- Used by config-manager-agent for parameter handling  
- Connected to all analyzer agents that require settings
- Provides validated configurations to main-agent

## Validation Requirements
- Check all numeric values are within acceptable ranges
- Validate boolean flags have correct values
- Ensure file paths exist and are accessible
- Verify tool parameters conform to expected formats