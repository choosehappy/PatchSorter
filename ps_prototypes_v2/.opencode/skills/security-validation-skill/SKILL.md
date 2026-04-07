---
name: security-validation
description: Define security validation rules and sandboxing approaches for code review processes
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: github
---
# Security Validation Skill

This skill defines security validation rules and sandboxing approaches for the code review process.

## Purpose
Establishes security measures to protect against malicious inputs and ensure safe execution.

## Rules and Standards
- Validate all file paths are within repository boundaries  
- Sanitize input data to prevent injection attacks
- Implement sandboxing for tool execution when possible
- Define acceptable resource usage limits

## Integration Points
- Used by validator-agent for security checks
- Connected to logger-agent for audit trails  
- Provides validation rules to error-handler-agent

## Validation Requirements
- All file paths must resolve within repository directory
- Commit references must be valid git objects
- Tool parameters must not contain malicious content
- Execution environments must have appropriate permissions

## Security Measures
- Path traversal prevention 
- Input sanitization and escaping
- Resource limit enforcement (CPU, memory, time)
- Isolated execution environment when possible