# PostToolUse Quality Hook Design

## Overview

A sophisticated PostToolUse hook system that automatically checks code quality (linting, type checking) and fixes issues after Claude Code edits files. The system features multi-stage fixing with traditional auto-fix tools and AI-powered Claude Code integration for complex issues.

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     Claude Code Editor                      │
└─────────────────────┬───────────────────────────────────────┘
                      │ PostToolUse Event
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    quality-hook.py                          │
│  • Input parsing & file extraction                          │
│  • Parallel quality checking orchestration                  │
│  • Multi-stage fix pipeline                                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
┌───────────────┐         ┌─────────────────┐
│ Traditional   │         │   Claude Code   │
│  Auto-Fix     │         │     Fixer       │
│ (auto_fix.py) │         │(claude_code_    │
│               │         │    fixer.py)    │
└───────────────┘         └─────────────────┘
```

### Hook Configuration

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|MultiEdit|Write|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/quality-hook.py"
          }
        ]
      }
    ]
  }
}
```

### Enhanced Input/Output Flow

```
Claude Code → Edit Tool → File Modified → PostToolUse Event
                                              ↓
                                        Quality Hook
                                              ↓
                              Parse Input JSON & Extract File Paths
                                              ↓
                    ┌─────────────────────────┴─────────────────────────┐
                    │              Iterative Fix Loop                     │
                    │          (max_fix_iterations times)                 │
                    │                                                     │
                    │     ┌──────────┴──────────┐                       │
                    │     │  Parallel Quality   │                       │
                    │     │      Checking        │                       │
                    │     │ (ThreadPoolExecutor)│                       │
                    │     └──────────┬──────────┘                       │
                    │                ↓                                   │
                    │     ┌──────────┴───────────┐                      │
                    │     │ Traditional Auto-Fix │                      │
                    │     │  (ruff --fix, etc)   │                      │
                    │     └──────────┬───────────┘                      │
                    │                ↓                                   │
                    │          Issues Remain?                            │
                    │           ┌────┴────┐                             │
                    │        No │         │ Yes                         │
                    │           ↓         ↓                             │
                    │       Success   Claude Code Fixer                 │
                    │                ┌────┴────┐                        │
                    │                │ Predict │                        │
                    │                │ Simple  │                        │
                    │                │  Fixes  │                        │
                    │                └────┬────┘                        │
                    │                     ↓                             │
                    │              ┌──────┴──────┐                     │
                    │              │   Cluster   │                     │
                    │              │   Issues    │                     │
                    │              └──────┬──────┘                     │
                    │                     ↓                             │
                    │        ┌────────────┴────────────┐               │
                    │        │ Git Worktree Parallel   │               │
                    │        │      Processing         │               │
                    │        └────────────┬────────────┘               │
                    │                     ↓                             │
                    │              ┌──────┴──────┐                     │
                    │              │    Merge    │                     │
                    │              │   Results   │                     │
                    │              └──────┬──────┘                     │
                    │                     ↓                             │
                    │                 Re-lint                           │
                    │                     ↓                             │
                    │            New Issues Found?                       │
                    │                ┌────┴────┐                        │
                    │             No │         │ Yes & < max iterations │
                    │                ↓         ↓                        │
                    │              Exit    Loop Back                    │
                    └───────────────────────────────────────────────────┘
                                              ↓
                                      Final Report
```

## Core Components

### 1. Main Hook (quality-hook.py)

**Key Features**:
- Parallel file processing with configurable workers
- Environment variable `CLAUDE_CODE_FIX_IN_PROGRESS` to prevent cascading hooks
- Comprehensive logging with rotation and multiple outputs
- Broken pipe handling for robustness
- Support for all Claude Code edit tools
- **Iterative fixing loop**: Automatically re-runs fixing process up to `max_fix_iterations` times when new issues are discovered after fixes

**Input Processing**:
```python
# Handles multiple input formats
- tool_input.file_path (Edit, Write)
- tool_input.filePath (alternative casing)
- tool_input.edits[].file_path (MultiEdit)
- tool_input.notebook_path (NotebookEdit)
```

### 2. Claude Code Integration (claude_code_fixer.py)

**Ultra-Optimized Features**:

#### Issue Clustering
- Groups related issues within `cluster_distance` lines (default: 5)
- Creates focused prompts for better context
- Reduces Claude API calls

#### Predictive Fixing
```python
simple_fix_patterns = {
    'F821': {  # Undefined name
        'json': 'import json',
        'datetime': 'from datetime import datetime',
        # ... more patterns
    },
    'F841': {  # Unused variable
        '_pattern': 'prefix_with_underscore'
    }
}
```

#### Git Worktree Parallelization
- Creates temporary git worktrees for conflict-free parallel processing
- Supports up to `max_worktrees` concurrent fixes
- Three merge strategies:
  1. **claude**: AI-powered intelligent merge
  2. **sequential**: Apply patches in order
  3. **octopus**: Git octopus merge

#### Merge Strategies

**Claude Merge** (Default):
```python
# Uses Claude to intelligently merge multiple fixes
# Handles complex conflicts and ensures all fixes are applied
# Creates comprehensive merge prompts with context
```

**Sequential Merge**:
```python
# Applies patches one by one using git apply --3way
# Falls back to Claude merge on conflicts
```

**Octopus Merge**:
```python
# Creates branches for each fix
# Uses git merge with multiple branches
```

### 3. Traditional Auto-Fix (auto_fix.py)

**Features**:
- Backup creation before fixes
- Diff generation for transparency
- Timeout handling (30 seconds)
- Restore on failure

## Configuration

### Complete Configuration Schema

```json
{
  "max_fix_iterations": 3,
  "auto_fix": {
    "enabled": true,
    "threshold": 10,
    "linters": {
      "ruff": true,
      "eslint": true,
      "rustfmt": true,
      "pylint": false
    }
  },
  "claude_code": {
    "enabled": true,
    "batch_mode": true,
    "max_issues_per_request": 5,
    "timeout": 600,
    "max_workers": 10,
    "max_fix_attempts": 3,

    // Optimization settings
    "predict_simple_fixes": true,
    "batch_similar_issues": true,
    "cluster_distance": 5,
    "use_memory_git": true,

    // Git worktree settings
    "use_git_worktrees": true,
    "worktree_merge_strategy": "claude",
    "cleanup_worktrees": true,
    "max_worktrees": 10,

    // Behavior settings
    "use_for_complex_issues": true,
    "fallback_when_autofix_fails": true
  },
  "severity_overrides": {
    "no-console": "warning",
    "max-line-length": "warning",
    "missing-docstring": "ignore",
    "F841": "error"
  },
  "logging": {
    "enabled": true,
    "level": "INFO"
  }
}
```

### Linter Configuration

**Language Mapping**:
```yaml
.py:
  primary: ruff
  fallback: [flake8, pylint, pycodestyle]
  auto-fix: true
  commands:
    ruff: ['ruff', 'check', '--output-format=json']
    flake8: ['flake8', '--format=json']
  fix_commands:
    ruff: ['ruff', 'check', '--fix', '--output-format=json']

.js, .jsx:
  primary: eslint
  fallback: [jshint, standard]
  auto-fix: true
  commands:
    eslint: ['eslint', '--format=json']
  fix_commands:
    eslint: ['eslint', '--fix', '--format=json']

.ts, .tsx:
  primary: eslint
  fallback: [tslint]
  auto-fix: true

.go:
  primary: golangci-lint
  fallback: [go vet, gofmt]
  auto-fix: false

.rs:
  primary: cargo clippy
  fallback: [rustfmt]
  auto-fix: true
```

## Response Handling

### Success States

**All Clean**:
```
✓ All files passed linting
```

**Auto-Fixed**:
```
✓ Auto-fixed 2 file(s):
  - src/main.py
  - src/utils.py
```

**Claude Fixed**:
```
🤖 Claude Code fixed 3 file(s)
```

### Warning States

**Non-blocking Issues**:
```
⚠ 5 warning(s) in 2 file(s) (non-blocking)
```

### Error States

**Blocking Errors** (Exit code 2):
```
Linting failed:

file.py:10:5: F821 Undefined name 'config'
file.py:15:1: E302 Expected 2 blank lines, found 1

Please fix these 2 error(s).
```

## Advanced Features

### Iterative Fixing

When syntax errors or other blocking issues prevent the linter from discovering all problems, the system can automatically iterate:

1. **Initial Run**: Fix syntax errors that block parsing
2. **Second Run**: Fix newly discovered issues after parsing succeeds
3. **Third Run**: Fix any remaining cascading issues

**Configuration**:
```json
{
  "max_fix_iterations": 3  // Maximum number of fix attempts
}
```

**Iteration Tracking**:
- Each iteration only re-lints files that had issues
- Progress is tracked to prevent infinite loops
- Stops early if no progress is made
- Provides summary of fixes per iteration

### Intelligent Issue Detection

The system identifies complex issues that require AI assistance:
- Undefined variables/functions
- Import errors
- Type mismatches
- Logic errors
- Complex refactoring needs

### Performance Optimizations

1. **Parallel Processing**:
   - Multiple files linted concurrently
   - Git worktrees for parallel fixing
   - ThreadPoolExecutor with configurable workers

2. **Caching**:
   - Linter availability
   - Configuration files
   - Simple fix patterns

3. **Smart Batching**:
   - Issue clustering
   - Similar issue grouping
   - Minimal Claude API calls

### Logging System

**Environment Variables**:
```bash
LINTER_HOOK_LOG_LEVEL=DEBUG
LINTER_HOOK_DISABLE_LOGGING=false
LINTER_HOOK_DISABLE_FILE_LOGGING=false
LINTER_HOOK_DISABLE_CONSOLE_LOGGING=false
```

**Log Locations**:
- File: `.claude/logs/quality-hook.log`
- Rotation: 10MB max, 5 backups
- Console: Errors only (by default)

## Security Considerations

- Path validation to prevent traversal attacks
- Command sanitization
- Timeout enforcement (30s per file, configurable total)
- Backup creation before modifications
- Git worktree isolation

## Extensibility

### Adding New Quality Checkers

1. Update `LINTERS` dictionary in `quality-hook.py`
2. Add command and fix_command configurations
3. Implement output parser if needed

### Custom Fix Patterns

Add to `simple_fix_patterns` in `claude_code_fixer.py`:
```python
'NEW_RULE': {
    'pattern_name': 'fix_string',
    '_pattern': 'special_handler'  # For complex patterns
}
```

## Future Enhancements

1. **Enhanced AI Integration**
   - Learning from fix history
   - Project-specific fix patterns
   - Team knowledge sharing

2. **Advanced Git Integration**
   - Automatic commit creation
   - PR-based fixing
   - Conflict resolution

3. **Performance Improvements**
   - Distributed processing
   - Cloud-based linting
   - Incremental type checking

4. **Developer Experience**
   - IDE integration
   - Real-time feedback
   - Fix suggestions with explanations

## Troubleshooting

### Common Issues

1. **Infinite Loop Prevention**:
   - Set by `max_fix_attempts` (default: 3)
   - Check `CLAUDE_CODE_FIX_IN_PROGRESS` environment variable

2. **Worktree Conflicts**:
   - Automatic cleanup on failure
   - Manual cleanup: `git worktree prune`

3. **Performance Issues**:
   - Adjust `max_workers` and `max_worktrees`
   - Reduce `cluster_distance`

### Debug Mode

Enable comprehensive debugging:
```json
{
  "logging": {
    "enabled": true,
    "level": "DEBUG"
  }
}
```

Check logs at `.claude/logs/quality-hook.log` for detailed execution traces.