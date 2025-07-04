# Security Policy

## Supported Versions

Currently, we support security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of Claude Code Quality Hook seriously. If you believe you've found a security vulnerability, please report it to us responsibly.

### How to Report

1. **DO NOT** open a public issue
2. Report security vulnerabilities using GitHub's private security advisory feature:
   - Go to the Security tab of this repository
   - Click on "Report a vulnerability"
   - Fill out the security advisory form
3. Include as much information as possible:
   - Type of issue (e.g., arbitrary code execution, command injection, etc.)
   - Full paths of source file(s) related to the issue
   - Step-by-step instructions to reproduce the issue
   - Proof-of-concept or exploit code (if possible)
   - Impact of the issue

### What to Expect

- We'll acknowledge receipt of your report within 48 hours
- We'll provide a more detailed response within 7 days
- We'll work with you to understand and resolve the issue
- We'll notify you when the issue is fixed
- We'll publicly acknowledge your responsible disclosure (unless you prefer to remain anonymous)

## Security Considerations

When using Claude Code Quality Hook, please be aware of:

1. **File System Access**: The hook has read/write access to your codebase
2. **External Commands**: The hook executes linter commands on your system
3. **API Calls**: When AI fixing is enabled, code snippets are sent to Claude
4. **Git Operations**: Worktree features create and manage git worktrees

### Best Practices

- Always review the hook's actions in your logs
- Use the configuration file to limit which features are enabled
- Be cautious when enabling AI-powered fixes on sensitive codebases
- Regularly update to the latest version for security patches

## Past Security Issues

No security issues have been reported yet. This section will be updated as issues are discovered and resolved.