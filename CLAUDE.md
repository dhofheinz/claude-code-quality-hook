# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a fully implemented PostToolUse quality hook system for Claude Code that automatically checks code quality (linting, type checking) and fixes issues after file edits. It features a sophisticated multi-stage pipeline with traditional auto-fixers and AI-powered Claude Code integration.

## Core Architecture

### Three-Stage Fix Pipeline

1. **Parallel Quality Checking** (`quality-hook.py`)
   - Runs appropriate linters based on file extension
   - Supports ruff + pyright for Python, eslint for JS/TS, golangci-lint for Go, cargo clippy for Rust
   - Parses diverse output formats (JSON, text) into standardized format

2. **Traditional Auto-Fix** (`auto_fix.py`)
   - Applies deterministic fixes using native linter commands (ruff --fix, eslint --fix)
   - Creates backups before modifications
   - Handles simple issues like formatting and import ordering

3. **AI-Powered Fixing** (`claude_code_fixer.py`)
   - Clusters related issues for context-aware fixes
   - Predicts simple fixes locally without API calls
   - Uses git worktrees for true parallel processing
   - Three merge strategies: claude (AI merge), sequential, octopus

### Key Architectural Decisions

- **Iterative Fixing**: Automatically re-runs up to `max_fix_iterations` times when fixing reveals new issues (e.g., syntax errors hiding import errors)
- **Issue Clustering**: Groups issues within `cluster_distance` lines for efficient batch fixing
- **Worktree Parallelization**: Creates isolated git worktrees for conflict-free parallel fixes
- **Type Checking Integration**: Runs Pyright alongside style checkers for comprehensive Python analysis

## Common Development Commands

```bash
# Initial setup - creates configs and tests installation
./setup.sh

# Test the hook manually (expects JSON input)
echo '{"tool_name":"Edit","tool_input":{"file_path":"test.py"}}' | ./quality-hook.py

# Run linters directly (for debugging)
ruff check --output-format=json file.py
pyright --outputjson file.py
eslint --format=json file.js

# Check logs for debugging
tail -f .claude/logs/quality-hook.log
```

## Configuration Files

- `.quality-hook.json` - Main configuration controlling fix behavior, iterations, and Claude integration
- `pyrightconfig.json` - Type checking strictness and Python version settings
- `.claude/settings.json` - Hook registration with Claude Code

## Critical Implementation Details

### Preventing Hook Cascading
The system sets `CLAUDE_CODE_FIX_IN_PROGRESS` environment variable to prevent infinite loops when Claude fixes trigger more edits.

### Pattern Matching for Claude Triggers
Complex issues that trigger AI fixes are identified by lowercase pattern matching in `should_use_claude()`. Patterns include Pyright rules like `reportargumenttype`, `reportmissingtypeargument`, etc.

### Git Worktree Management
When `use_git_worktrees` is enabled:
- Files must be in git (uses `git add -N` for new files)
- Creates worktrees in `.claude/worktrees/`
- Always cleans up worktrees, even on failure
- Supports three merge strategies for combining parallel fixes

### Predictive Fixes
Common patterns are fixed locally without calling Claude:
- F821 (undefined name) → adds standard imports
- F841 (unused variable) → prefixes with underscore
- Configured in `simple_fix_patterns` dictionary

## Testing and Debugging

Enable debug logging in `.quality-hook.json`:
```json
{
  "logging": {
    "enabled": true,
    "level": "DEBUG"
  }
}
```

Common issues:
- "Linter not found" - Check PATH includes `~/.local/bin`, `~/.npm-global/bin`
- "No progress made" - Often due to circular dependencies or logical code issues
- "Worktree creation failed" - Ensure files are committed to git

## Performance Considerations

- Parallel linting with ThreadPoolExecutor (default 4 workers)
- Issue clustering reduces Claude API calls
- Predictive fixes avoid API calls for common patterns
- Git worktrees enable true parallel fixing (up to `max_worktrees`)
- Timeout protection: 30s per linter, 600s per Claude fix