# Contributing to Claude Code Quality Hook

First off, thank you for considering contributing to Claude Code Quality Hook! It's people like you that make this tool better for everyone.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When you create a bug report, include as many details as possible:

- **Use a clear and descriptive title**
- **Describe the exact steps to reproduce the problem**
- **Provide specific examples** (include code samples, error messages, logs)
- **Describe the behavior you observed vs. what you expected**
- **Include your environment details** (OS, Python version, Claude Code version, linter versions)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

- **Use a clear and descriptive title**
- **Provide a detailed description** of the suggested enhancement
- **Explain why this enhancement would be useful** to most users
- **List any alternative solutions** you've considered

### Pull Requests

1. **Fork the repo** and create your branch from `main`
2. **Write clear, commented code** that follows the existing style
3. **Add tests** if you're adding features
4. **Update documentation** as needed
5. **Ensure all tests pass** and the code lints cleanly
6. **Write a clear PR description** explaining your changes

## Development Setup

```bash
# Clone your fork
git clone https://github.com/your-username/claude-code-quality-hook.git
cd claude-code-quality-hook

# Run setup
./setup.sh

# Create a test file to trigger the hook
echo "print('test')" > test.py

# Test the hook manually
echo '{"tool_name":"Edit","tool_input":{"file_path":"test.py"}}' | ./quality-hook.py
```

## Testing

Before submitting a PR:

1. **Test with multiple file types** (Python, JavaScript, Go, Rust)
2. **Test both checking and fixing features**
3. **Test with various linter configurations**
4. **Verify git worktree operations** if modifying that code
5. **Check logs** for any errors or warnings

## Code Style

- **Python**: Follow PEP 8, use type hints where appropriate
- **Comments**: Write clear comments for complex logic
- **Functions**: Keep functions focused and under 50 lines when possible
- **Error handling**: Always clean up resources (especially git worktrees)

## Adding New Linter Support

To add support for a new language/linter:

1. Add the linter configuration to `run_linters()` in `quality-hook.py`
2. Add parser logic to handle the linter's output format
3. Add auto-fix support in `auto_fix.py` if the linter supports it
4. Update documentation with the new linter details
5. Add example configuration to the relevant `.example` files

## Documentation

- Update `README.md` for user-facing changes
- Update `CLAUDE.md` for implementation details
- Update `quality-hook-design.md` for architectural changes
- Include docstrings for new functions/classes

## Questions?

Feel free to open an issue with the "question" label if you need clarification on anything.

Thank you for contributing! 🎉