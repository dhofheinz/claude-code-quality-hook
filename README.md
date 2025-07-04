# Claude Code Quality Hook

A sophisticated PostToolUse hook system that automatically checks code quality (linting, type checking) and fixes issues after Claude Code edits files. It features a three-stage pipeline with traditional auto-fixers and AI-powered Claude Code integration.

## Key Features

- **🚀 Automatic Code Quality Checks** - Runs appropriate linters and type checkers after every file edit
- **🔧 Three-Stage Fix Pipeline** - Parallel quality checking, traditional auto-fix, and AI-powered fixing
- **⚡ Git Worktree Parallelization** - True parallel processing without file conflicts
- **🔄 Iterative Fixing** - Automatically re-runs up to `max_fix_iterations` times when fixes reveal new issues
- **🎯 Smart Issue Clustering** - Groups related issues for context-aware fixes
- **🧠 Predictive Fixes** - Common issues fixed locally without API calls
- **📊 Type Checking** - Integrated Pyright support for comprehensive Python type analysis

## Quick Start

### 1. Run Setup Script

```bash
./setup.sh
```

This will:
- Make scripts executable
- Create `.claude/settings.json` with hook configuration
- Create `.quality-hook.json` with default settings
- Test the installation

### 2. Install Required Linters

```bash
# Python
pip install ruff
npm install -g pyright  # For type checking (Pylance core)

# JavaScript/TypeScript
npm install -g eslint

# Go
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest

# Rust
rustup component add clippy rustfmt
```

### 3. Test the Hook

Make an edit with Claude Code and watch the automatic linting and fixing in action!

## How It Works

### Architecture Overview

```
Claude Code Edit → PostToolUse Hook → Linter Hook
                                           ↓
                                    Parallel Linting
                                           ↓
                                    Traditional Auto-Fix
                                           ↓
                                    Claude Code AI Fix
                                           ↓
                                    Iterative Re-check
```

### Multi-Stage Fixing Pipeline

#### Stage 1: Traditional Auto-Fix
Fast, deterministic fixes using native linter commands:
- `ruff check --fix` for Python
- `eslint --fix` for JavaScript/TypeScript
- `rustfmt` for Rust
- Creates backups before modifying files
- Handles simple formatting and import ordering

#### Stage 2: AI-Powered Fixing
Claude Code handles complex issues that auto-fixers can't:
- **Predictive Fixes**: Common patterns fixed locally without API calls
- **Issue Clustering**: Groups nearby issues for context-aware fixes
- **Parallel Processing**: Uses git worktrees for true parallelization
- **Intelligent Merging**: Multiple fixes merged without conflicts

#### Stage 3: Iterative Refinement
Automatically re-runs the pipeline when:
- Syntax errors hid other issues
- Fixes introduce new linting problems
- Up to `max_fix_iterations` times (default: 3)

## Configuration

### Basic Configuration (`.quality-hook.json`)

```json
{
  "max_fix_iterations": 3,
  "auto_fix": {
    "enabled": true,
    "threshold": 10,
    "linters": {
      "ruff": true,
      "eslint": true,
      "rustfmt": true
    }
  },
  "claude_code": {
    "enabled": true,
    "use_git_worktrees": true,
    "predict_simple_fixes": true
  }
}
```

### Advanced Configuration

See `.quality-hook.json.example` for all available options including:
- Performance tuning (workers, timeouts, clustering)
- Git worktree strategies (claude, sequential, octopus)
- Severity overrides per linting rule
- Logging configuration

## Supported Languages & Linters

| Language | Primary Linter | Auto-Fix | Fallback Linters |
|----------|---------------|----------|------------------|
| Python | ruff | ✅ | pyright (type checking), flake8, pylint, pycodestyle |
| JavaScript | eslint | ✅ | jshint, standard |
| TypeScript | eslint | ✅ | tslint |
| Go | golangci-lint | ❌ | go vet, gofmt |
| Rust | cargo clippy | ❌ | rustfmt (✅) |

## Advanced Features

### Type Checking with Pyright/Pylance

The linter hook now integrates with Pyright (the core of VS Code's Pylance) to provide comprehensive type checking alongside traditional linting:

**Features**:
- Runs automatically for Python files when Pyright is installed
- Detects type mismatches, missing type arguments, undefined variables
- Claude Code can fix complex type issues that traditional tools can't
- Works seamlessly with existing linters like ruff

**Example Type Issues Fixed**:
```python
# Before - Type errors
def process(data):
    result: str = calculate_sum(1, 2)  # Type error: int != str
    return result.upper()

# After - Claude Code fixes
def process(data: Any) -> str:
    result: int = calculate_sum(1, 2)
    return str(result).upper()
```

**Configuration**:
- Type checking is enabled by default in `.quality-hook.json`
- For Pyright-specific settings, create a `pyrightconfig.json` (see `pyrightconfig.json.example`)
- Pyright config is optional - it will use sensible defaults if not present

### Git Worktree Parallelization

When enabled, the system creates isolated git worktrees for each fix cluster:
- True parallel processing without file conflicts
- Three merge strategies: claude (AI), sequential, octopus
- Automatic cleanup of temporary worktrees
- Requires git repository

### Predictive Fixing

Common issues are fixed instantly without calling Claude:
- Missing imports (e.g., `import json` for undefined `json`)
- Unused variables (prefix with underscore)
- Import order issues
- Configurable patterns in `claude_code_fixer.py`

### Issue Clustering

Related issues within 5 lines are grouped together:
- Provides better context for fixes
- Reduces API calls
- Prevents conflicting fixes
- Configurable via `cluster_distance`

## Example Workflows

### Simple Python Formatting
```
1. Edit: main.py with inconsistent formatting
2. Ruff detects 5 style issues
3. Auto-fix: `ruff check --fix` resolves all issues
4. ✅ Complete in <1 second
```

### Complex TypeScript Imports
```
1. Edit: app.tsx with broken imports
2. ESLint detects undefined components
3. Auto-fix: No fixes available
4. Claude Code: Analyzes and fixes import paths
5. ✅ Complete in ~5 seconds
```

### Cascading Python Issues
```
1. Edit: test.py with syntax error
2. Ruff detects 1 syntax error
3. Claude Code: Fixes syntax error
4. Iteration 2: Ruff now detects 10 import errors
5. Predictive fixes: 8 common imports added instantly
6. Claude Code: Fixes 2 complex import issues
7. ✅ Complete in ~10 seconds with 3 iterations
```

## Performance & Optimization

- **Parallel Linting**: 4 concurrent workers by default
- **Smart Caching**: Skip unchanged files
- **Batch Processing**: Multiple files in single Claude session
- **Timeout Protection**: 30s per linter, 600s per Claude fix
- **Resource Cleanup**: Automatic worktree and backup cleanup

## Troubleshooting

### Enable Debug Logging
```json
{
  "logging": {
    "enabled": true,
    "level": "DEBUG"
  }
}
```

Logs are saved to `.claude/logs/quality-hook.log`

### Common Issues

1. **"Linter not found"**
   - Install the required linter
   - Ensure it's in your PATH
   - Check `~/.local/bin` is in PATH

2. **"Max fix attempts exceeded"**
   - Complex circular dependencies
   - Increase `max_fix_attempts`
   - Check for logical code issues

3. **"Worktree creation failed"**
   - Not in a git repository
   - Uncommitted changes blocking worktree
   - Set `use_git_worktrees: false`

### Environment Variables

- `LINTER_HOOK_LOG_LEVEL` - Override log level
- `LINTER_HOOK_DISABLE_LOGGING` - Disable all logging
- `CLAUDE_CODE_FIX_IN_PROGRESS` - Internal flag (don't set manually)

## Security Considerations

- All file modifications are logged
- Backups created before any changes
- Linter commands are not shell-interpreted
- Path validation prevents directory traversal
- Timeout protection against hanging processes

## Contributing

To contribute to this project:
1. Test changes with multiple file types
2. Ensure backward compatibility
3. Update documentation and examples
4. Add tests for new linters

## License

This is an independent project. See LICENSE file for details.