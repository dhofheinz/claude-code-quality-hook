# Changelog

All notable changes to Claude Code Quality Hook will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2025-01-03

First stable release of Claude Code Quality Hook - a PostToolUse hook that automatically checks and fixes code quality issues after file edits.

### Added

- Multi-stage quality pipeline: parallel linting, traditional auto-fix, and AI-powered fixing
- Language support for Python (ruff, Pyright), JavaScript/TypeScript (ESLint), Go (golangci-lint), and Rust (cargo clippy)
- Git worktree support for parallel Claude Code processing without file conflicts
- Issue clustering to group related problems for efficient batch fixing
- Predictive local fixes for common patterns (missing imports, unused variables)
- Iterative fixing with configurable `max_fix_iterations` for cascading issues
- Multiple merge strategies: `claude` (AI-powered), `sequential`, and `octopus`
- Pyright type checking integration with support for 15+ error patterns
- Comprehensive `.quality-hook.json` configuration system
- Environment variable `CLAUDE_CODE_FIX_IN_PROGRESS` to prevent hook cascading

### Security
- Timeout protection (30s per linter, 600s per Claude fix)
- Automatic file backups before modifications
- Safe error handling with process isolation

---

### [0.0.9] - 2024-12-15

#### Added
- Type checking configuration toggle in `.quality-hook.json`
- Pyright documentation and examples
- `pyrightconfig.json` template
- Pyright-specific severity overrides

#### Fixed
- POSIX compliance in configuration files
- Configuration template formatting

### [0.0.8] - 2024-12-08

#### Added
- Pyright type checking integration for Python files
- Support for 15+ Pyright error patterns in Claude Code fixer
- Expanded PATH search for npm global installations

#### Fixed
- Case-insensitive error pattern matching
- Pyright JSON output parsing

### [0.0.7] - 2024-12-01

#### Added
- Troubleshooting guide
- Workflow examples in documentation

#### Changed
- Rewrote README for clarity
- Updated configuration file handling

#### Fixed
- `.gitignore` to properly track configuration files

### [0.0.6] - 2024-11-24

#### Changed
- Consolidated example configuration files
- Updated setup script
- Refactored auto-fix module

#### Removed
- Duplicate example files
- References to deprecated features

### [0.0.5] - 2024-11-17

#### Removed
- Development test files (`test_*.py`, `performance_test.py`)
- Sample data files
- Temporary development artifacts

### [0.0.4] - 2024-11-10

#### Added
- Iterative fixing system with `max_fix_iterations` configuration
- Progress detection to handle cascading issues
- Per-iteration fix tracking and reporting

#### Fixed
- Variable scope issues in worktree operations
- Worktree cleanup in error paths
- Edge cases in parallel processing

### [0.0.3] - 2024-11-03

#### Changed
- Simplified to full-file linting only
- Streamlined codebase architecture

#### Removed
- Incremental linting feature
- Associated complexity

### [0.0.2] - 2024-10-27

#### Added
- Git worktree support for parallel Claude Code processing
- Three merge strategies: `claude`, `sequential`, `octopus`
- Automatic worktree cleanup
- Support for uncommitted files with `git add -N`

#### Fixed
- Claude Code fixer initialization
- Module import errors

### [0.0.1] - 2024-10-20

#### Added
- Initial PostToolUse hook implementation
- Multi-language linting support
- Claude Code integration
- Configuration system (`.quality-hook.json`)
- Parallel file processing with ThreadPoolExecutor
- Logging with rotation
- Issue clustering algorithm


[Unreleased]: https://github.com/dhofheinz/claude-code-quality-hook/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dhofheinz/claude-code-quality-hook/releases/tag/v0.1.0