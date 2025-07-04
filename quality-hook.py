#!/usr/bin/env python3
"""
PostToolUse Quality Hook for Claude Code
Automatically checks code quality (linting, type checking) and fixes issues
Version: 1.0.0
"""
import json
import sys
import os
import subprocess
import time
import logging
import logging.handlers
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add common user binary locations to PATH
user_paths = [
    os.path.expanduser('~/.local/bin'),
    os.path.expanduser('~/.npm-global/bin'),
    os.path.expanduser('~/node_modules/.bin'),
    '/usr/local/bin'
]
if 'PATH' in os.environ:
    os.environ['PATH'] = ':'.join(user_paths) + ':' + os.environ['PATH']
else:
    os.environ['PATH'] = ':'.join(user_paths)


# Import auto-fix support
try:
    from auto_fix import AutoFixer, get_fix_command, format_auto_fix_result
    _auto_fix_enabled = True
except ImportError:
    _auto_fix_enabled = False
    AutoFixer = None  # type: ignore
    # Provide type-safe stubs when imports fail
    def get_fix_command(linter: str, linter_config: Dict[str, Any]) -> Optional[List[str]]:
        return None
    def format_auto_fix_result(results: List[Dict[str, Any]]) -> str:
        return ""

# Import Claude Code integration
try:
    from claude_code_fixer import ClaudeCodeFixer, format_claude_fix_result
    _claude_code_enabled = True
except ImportError:
    _claude_code_enabled = False
    ClaudeCodeFixer = None  # type: ignore
    def format_claude_fix_result(results: List[Dict[str, Any]]) -> str:
        return ""

# Export as constants for backward compatibility
AUTO_FIX_ENABLED = _auto_fix_enabled
CLAUDE_CODE_ENABLED = _claude_code_enabled

# Global configuration cache for efficiency
CONFIG_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

# Configuration
TIMEOUT_SECONDS = 30  # Timeout for each linter command
MAX_WORKERS = 4
LOG_DIR = Path.cwd() / '.claude' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Worktrees are stored in .claude/worktrees/ when enabled

# Linter configurations
LINTERS = {
    '.py': {
        'primary': 'ruff',
        'fallback': ['pyright', 'flake8', 'pylint', 'pycodestyle'],
        'auto_fix': True,
        'commands': {
            'ruff': ['ruff', 'check', '--output-format=json'],
            'pyright': ['pyright', '--outputjson'],
            'flake8': ['flake8', '--format=json'],
            'pylint': ['pylint', '--output-format=json'],
            'pycodestyle': ['pycodestyle', '--format=%(path)s:%(row)d:%(col)d: %(code)s %(text)s']
        },
        'fix_commands': {
            'ruff': ['ruff', 'check', '--fix', '--output-format=json']
        }
    },
    '.js': {
        'primary': 'eslint',
        'fallback': ['jshint', 'standard'],
        'auto_fix': True,
        'commands': {
            'eslint': ['eslint', '--format=json'],
            'jshint': ['jshint', '--reporter=unix'],
            'standard': ['standard', '--verbose']
        },
        'fix_commands': {
            'eslint': ['eslint', '--fix', '--format=json']
        }
    },
    '.jsx': {
        'primary': 'eslint',
        'fallback': ['jshint'],
        'auto_fix': True,
        'commands': {
            'eslint': ['eslint', '--format=json'],
            'jshint': ['jshint', '--reporter=unix']
        },
        'fix_commands': {
            'eslint': ['eslint', '--fix', '--format=json']
        }
    },
    '.ts': {
        'primary': 'eslint',
        'fallback': ['tslint'],
        'auto_fix': True,
        'commands': {
            'eslint': ['eslint', '--format=json'],
            'tslint': ['tslint', '--format=json']
        },
        'fix_commands': {
            'eslint': ['eslint', '--fix', '--format=json']
        }
    },
    '.tsx': {
        'primary': 'eslint',
        'fallback': ['tslint'],
        'auto_fix': True,
        'commands': {
            'eslint': ['eslint', '--format=json'],
            'tslint': ['tslint', '--format=json']
        },
        'fix_commands': {
            'eslint': ['eslint', '--fix', '--format=json']
        }
    },
    '.go': {
        'primary': 'golangci-lint',
        'fallback': ['go vet', 'gofmt'],
        'auto_fix': False,
        'commands': {
            'golangci-lint': ['golangci-lint', 'run', '--out-format=json'],
            'go vet': ['go', 'vet'],
            'gofmt': ['gofmt', '-l']
        }
    },
    '.rs': {
        'primary': 'cargo clippy',
        'fallback': ['rustfmt'],
        'auto_fix': True,
        'commands': {
            'cargo clippy': ['cargo', 'clippy', '--message-format=json'],
            'rustfmt': ['rustfmt', '--check']
        },
        'fix_commands': {
            'rustfmt': ['rustfmt']
        }
    }
}

# Blocking error patterns
BLOCKING_PATTERNS = {
    'syntax_error', 'SyntaxError', 'ParseError', 'CompileError',
    'ImportError', 'ModuleNotFoundError', 'undefined', 'ReferenceError',
    'TypeError', 'NameError', 'security', 'sql-injection', 'xss',
    # Pyright/Pylance type errors
    'reportGeneralTypeIssues', 'reportArgumentType', 'reportAssignmentType',
    'reportReturnType', 'reportIndexIssue', 'reportOptionalMemberAccess',
    'reportMissingTypeArgument', 'reportPossiblyUnboundVariable',
    'reportConstantRedefinition', 'reportCallIssue', 'reportAttributeAccessIssue',
    'reportUnknownParameterType', 'reportUnknownMemberType'
}


def setup_logging() -> logging.Logger:
    """Setup logging with file rotation and proper formatting"""
    logger = logging.getLogger('quality-hook')
    
    # Check if logging is disabled
    if os.environ.get('LINTER_HOOK_DISABLE_LOGGING', '').lower() in ('true', '1', 'yes'):
        logger.addHandler(logging.NullHandler())
        return logger
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Get log level from environment or default to INFO
    log_level = os.environ.get('LINTER_HOOK_LOG_LEVEL', 'INFO').upper()
    if log_level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
        log_level = 'INFO'
    logger.setLevel(getattr(logging, log_level))
    
    # Check if file logging is disabled
    if os.environ.get('LINTER_HOOK_DISABLE_FILE_LOGGING', '').lower() not in ('true', '1', 'yes'):
        # Create formatters
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # File handler with rotation
        log_file = LOG_DIR / 'quality-hook.log'
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    # Console handler for errors only (unless disabled)
    if os.environ.get('LINTER_HOOK_DISABLE_CONSOLE_LOGGING', '').lower() not in ('true', '1', 'yes'):
        console_formatter = logging.Formatter('%(levelname)s - %(message)s')
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    return logger


# Initialize logger
logger = setup_logging()


def get_linter_availability(linter_name: str) -> bool:
    """Check if a linter is available"""
    try:
        cmd = linter_name.split()[0]
        logger.debug(f"Checking availability of linter: {linter_name}")
        subprocess.run(['which', cmd], capture_output=True, check=True)
        logger.debug(f"Linter {linter_name} is available")
        return True
    except subprocess.CalledProcessError:
        logger.debug(f"Linter {linter_name} is not available")
        return False


def extract_file_paths(tool_input: Dict[str, Any]) -> List[str]:
    """Extract file paths from tool input"""
    paths: List[str] = []
    
    # Standard file_path field
    if 'file_path' in tool_input:
        paths.append(tool_input['file_path'])
    elif 'filePath' in tool_input:
        paths.append(tool_input['filePath'])
    
    # MultiEdit support
    if 'edits' in tool_input and isinstance(tool_input['edits'], list):
        for edit in tool_input['edits']:
            if isinstance(edit, dict) and 'file_path' in edit:
                paths.append(edit['file_path'])
    
    # NotebookEdit support
    if 'notebook_path' in tool_input:
        paths.append(tool_input['notebook_path'])
    
    unique_paths: List[str] = list(set(paths))  # Remove duplicates
    logger.debug(f"Extracted {len(unique_paths)} file path(s): {unique_paths}")
    return unique_paths


def load_configuration() -> Dict[str, Any]:
    """Load configuration with caching"""
    config_files = [
        Path('.quality-hook.json'),
        Path.home() / '.claude' / 'linter-config.json'
    ]
    
    for config_file in config_files:
        if config_file.exists():
            mtime = config_file.stat().st_mtime
            cache_key = str(config_file)
            
            if cache_key in CONFIG_CACHE:
                cached_mtime: float
                cached_config: Dict[str, Any]
                cached_mtime, cached_config = CONFIG_CACHE[cache_key]
                if cached_mtime == mtime:
                    logger.debug(f"Using cached config from {config_file}")
                    return cached_config
            
            try:
                with open(config_file) as f:
                    config = json.load(f)
                    CONFIG_CACHE[cache_key] = (mtime, config)
                    logger.info(f"Loaded configuration from {config_file}")
                    return config
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse config file {config_file}: {e}")
    
    logger.debug("Using default configuration")
    return {}






def run_linter_with_timeout(cmd: List[str], file_path: str, timeout: int = TIMEOUT_SECONDS) -> Tuple[int, str, str]:
    """Run linter with timeout"""
    start_time = time.time()
    full_cmd = cmd + [file_path]
    logger.debug(f"Running linter command: {' '.join(full_cmd)}")
    
    proc = None
    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        elapsed = time.time() - start_time
        logger.debug(f"Linter completed in {elapsed:.2f}s with return code {proc.returncode}")
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
        logger.warning(f"Linter timeout after {timeout}s for {file_path}")
        return -1, "", "Linter timeout"
    except Exception as e:
        logger.error(f"Error running linter: {e}")
        return -1, "", str(e)


def parse_linter_output(linter: str, output: str, stderr: str) -> List[Dict[str, Any]]:
    """Parse linter output into standardized format"""
    issues: List[Dict[str, Any]] = []
    
    logger.debug(f"Parsing {linter} output. Output length: {len(output)}, stderr length: {len(stderr)}")
    logger.debug(f"Raw output: {output[:500]}")  # First 500 chars
    
    try:
        if linter in ['ruff', 'eslint', 'tslint', 'pylint', 'pyright']:
            # JSON output
            if output.strip():
                data: Union[List[Dict[str, Any]], Dict[str, Any]] = json.loads(output)
                logger.debug(f"Parsed JSON data type: {type(data)}, length: {len(data)}")
                if isinstance(data, list):
                    # Check if it's ruff's format (array of issues)
                    if data and 'location' in data[0]:
                        # Ruff format - array of issues
                        for issue in data:
                            code: str = issue.get('code', '')
                            location: Dict[str, Any] = issue.get('location', {})
                            issues.append({
                                'line': location.get('row', 0),
                                'column': location.get('column', 0),
                                'severity': 'error',  # Ruff issues are generally errors
                                'message': issue.get('message', ''),
                                'rule': code
                            })
                    else:
                        # ESLint format
                        for file_data in data:
                            messages: List[Dict[str, Any]] = file_data.get('messages', [])
                            for msg in messages:
                                issues.append({
                                    'line': msg.get('line', 0),
                                    'column': msg.get('column', 0),
                                    'severity': msg.get('severity', 'error'),
                                    'message': msg.get('message', ''),
                                    'rule': msg.get('ruleId', '')
                                })
                else:
                    # Check if it's Pyright format
                    if 'generalDiagnostics' in data:
                        # Pyright format
                        diagnostics: List[Dict[str, Any]] = data.get('generalDiagnostics', [])
                        # diagnostics is already typed as List[Dict[str, Any]]
                        for diag in diagnostics:
                            severity_map = {
                                'error': 'error',
                                'warning': 'warning',
                                'information': 'warning',
                                'hint': 'warning'
                            }
                            range_data: Dict[str, Any] = diag.get('range', {})
                            # range_data is already typed as Dict[str, Any]
                            if range_data:
                                start_data: Dict[str, Any] = range_data.get('start', {})
                                # start_data is already typed as Dict[str, Any]
                                if start_data:
                                    issues.append({
                                        'line': start_data.get('line', 0) + 1,
                                        'column': start_data.get('character', 0) + 1,
                                        'severity': severity_map.get(diag.get('severity', 'error'), 'error'),
                                        'message': diag.get('message', ''),
                                        'rule': diag.get('rule', '')
                                    })
                    else:
                        # Old Ruff format
                        issue_list: List[Dict[str, Any]] = data.get('issues', [])
                        # issue_list is already typed as List[Dict[str, Any]]
                        for issue in issue_list:
                            location: Dict[str, Any] = issue.get('location', {})
                            # location is already typed as Dict[str, Any]
                            if location:
                                code: str = issue.get('code', '')
                                # code is already typed as str
                                if code:
                                    issues.append({
                                        'line': location.get('row', 0),
                                        'column': location.get('column', 0),
                                        'severity': 'error' if code.startswith('E') else 'warning',
                                        'message': issue.get('message', ''),
                                        'rule': code
                                    })
        else:
            # Text output parsing
            for line in output.split('\n'):
                if ':' in line and len(line.split(':')) >= 4:
                    parts = line.split(':')
                    try:
                        issues.append({
                            'line': int(parts[1]),
                            'column': int(parts[2]) if len(parts) > 2 else 0,
                            'severity': 'error',
                            'message': ':'.join(parts[3:]).strip(),
                            'rule': ''
                        })
                    except ValueError:
                        pass
    except Exception as e:
        logger.error(f"Failed to parse {linter} output: {e}", exc_info=True)
        # Fallback: treat any output as an issue
        if output.strip() or stderr.strip():
            issues.append({
                'line': 0,
                'column': 0,
                'severity': 'error',
                'message': output.strip() or stderr.strip(),
                'rule': ''
            })
    
    return issues


def is_blocking_issue(issue: Dict[str, Any]) -> bool:
    """Determine if an issue should block the change"""
    message = issue.get('message', '').lower()
    rule = issue.get('rule', '').lower()
    
    for pattern in BLOCKING_PATTERNS:
        if pattern.lower() in message or pattern.lower() in rule:
            return True
    
    return issue.get('severity') == 'error'


def lint_file(file_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Lint a single file efficiently"""
    ext = Path(file_path).suffix
    logger.info(f"Linting file: {file_path} (extension: {ext})")
    
    if ext not in LINTERS:
        logger.info(f"No linter configured for extension {ext}")
        return {'success': True, 'issues': [], 'linter': None}
    
    linter_config = LINTERS[ext]
    
    # Check if we should run type checking alongside style checking
    run_type_checking = config.get('type_checking', {}).get('enabled', True)
    type_checkers = []
    
    if ext == '.py' and run_type_checking:
        # For Python, always run pyright if available
        type_checkers = ['pyright']
    
    # Collect all issues from all linters
    all_issues: List[Dict[str, Any]] = []
    linters_used: List[str] = []
    
    # First, run the primary linter
    primary_linter = linter_config['primary']
    if isinstance(primary_linter, str) and get_linter_availability(primary_linter):
        commands = linter_config.get('commands', {})
        if isinstance(commands, dict):
            cmd = commands.get(primary_linter, [])
            if cmd:
                returncode, stdout, stderr = run_linter_with_timeout(cmd, file_path)
                if returncode != -1:  # If not timeout/error
                    issues = parse_linter_output(primary_linter, stdout, stderr)
                    logger.debug(f"Parsed {len(issues)} issues from {primary_linter} for {file_path}")
                    all_issues.extend(issues)
                    linters_used.append(primary_linter)
                    
                    if issues:
                        logger.info(f"Lint found {len(issues)} issue(s) in {file_path} using {primary_linter}")
                    else:
                        logger.info(f"Lint passed for {file_path} using {primary_linter}")
    
    # Then run type checkers if enabled
    for type_checker in type_checkers:
        if type_checker not in linters_used and get_linter_availability(type_checker):
            commands = linter_config.get('commands', {})
            if isinstance(commands, dict):
                cmd = commands.get(type_checker, [])
                if cmd:
                    returncode, stdout, stderr = run_linter_with_timeout(cmd, file_path)
                    if returncode != -1:  # If not timeout/error
                        issues = parse_linter_output(type_checker, stdout, stderr)
                        logger.debug(f"Parsed {len(issues)} type issues from {type_checker} for {file_path}")
                        all_issues.extend(issues)
                        linters_used.append(type_checker)
                        
                        if issues:
                            logger.info(f"Type check found {len(issues)} issue(s) in {file_path} using {type_checker}")
                        else:
                            logger.info(f"Type check passed for {file_path} using {type_checker}")
    
    # If primary linter failed, try fallbacks
    if not linters_used:
        fallback_linters = linter_config.get('fallback', [])
        if isinstance(fallback_linters, list):
            for linter in fallback_linters:
                if not get_linter_availability(linter):
                    continue
                
                commands = linter_config.get('commands', {})
                if not isinstance(commands, dict):
                    continue
                cmd = commands.get(linter, [])
                if not cmd:
                    continue
                
                returncode, stdout, stderr = run_linter_with_timeout(cmd, file_path)
                
                if returncode == -1:  # Timeout or error
                    continue
                
                issues = parse_linter_output(linter, stdout, stderr)
                logger.debug(f"Parsed {len(issues)} issues from {linter} for {file_path}")
                all_issues.extend(issues)
                linters_used.append(linter)
                
                if issues:
                    logger.info(f"Lint found {len(issues)} issue(s) in {file_path} using {linter}")
                else:
                    logger.info(f"Lint passed for {file_path} using {linter}")
                
                break  # Use first working fallback
    
    result = {
        'success': len(all_issues) == 0,
        'issues': all_issues,
        'linter': ', '.join(linters_used) if linters_used else None,
        'file': file_path
    }
    
    logger.debug(f"Result success: {result['success']}, total issues: {len(all_issues)}")
    
    return result


def lint_files_parallel(file_paths: List[str], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lint multiple files in parallel"""
    results: List[Dict[str, Any]] = []
    start_time = time.time()
    logger.info(f"Starting parallel linting of {len(file_paths)} file(s) with {MAX_WORKERS} workers")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {
            executor.submit(lint_file, file_path, config): file_path
            for file_path in file_paths
        }
        
        for future in as_completed(future_to_file):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                file_path = future_to_file[future]
                logger.error(f"Failed to lint {file_path}: {e}", exc_info=True)
                results.append({
                    'success': False,
                    'issues': [{
                        'line': 0,
                        'column': 0,
                        'severity': 'error',
                        'message': f'Linting failed: {str(e)}',
                        'rule': ''
                    }],
                    'linter': None,
                    'file': file_path
                })
    
    elapsed = time.time() - start_time
    logger.info(f"Parallel linting completed in {elapsed:.2f}s")
    return results


def format_output(results: List[Dict[str, Any]]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Format linting results for output"""
    all_issues: List[Dict[str, Any]] = []
    blocking_issues: List[Dict[str, Any]] = []
    files_with_issues: List[str] = []
    
    logger.info(f"Processing lint results for {len(results)} file(s)")
    
    for result in results:
        if result['issues']:
            files_with_issues.append(result['file'])
            for issue in result['issues']:
                issue['file'] = result['file']
                all_issues.append(issue)
                if is_blocking_issue(issue):
                    blocking_issues.append(issue)
    
    if not all_issues:
        logger.info("All files passed linting successfully")
        return True, "✓ All files passed linting", None
    
    # Format issues
    if blocking_issues:
        logger.info(f"Found {len(blocking_issues)} blocking issue(s) in {len(files_with_issues)} file(s)")
        message = "Linting failed:\n\n"
        for issue in blocking_issues:
            message += f"{issue['file']}:{issue['line']}:{issue['column']}: "
            if issue['rule']:
                message += f"{issue['rule']} "
            message += f"{issue['message']}\n"
        
        message += f"\nPlease fix these {len(blocking_issues)} error(s)."
        
        return False, "", {
            "decision": "block",
            "reason": message
        }
    else:
        # Only warnings
        warning_count = len(all_issues)
        file_count = len(files_with_issues)
        logger.info(f"Found {warning_count} non-blocking warning(s) in {file_count} file(s)")
        message = f"⚠ {warning_count} warning(s) in {file_count} file(s) (non-blocking)"
        
        return True, message, None


def main():
    """Main entry point"""
    try:
        # Check if we're being called from within a Claude fix operation
        if os.environ.get('CLAUDE_CODE_FIX_IN_PROGRESS'):
            logger.info("Detected Claude Code fix in progress, skipping hook to prevent cascading")
            print(json.dumps({"suppressOutput": True}))
            return 0
        
        logger.info("Linter hook started")
        # Read input
        input_data = json.load(sys.stdin)
        logger.debug(f"Received input: {json.dumps(input_data, indent=2)}")
        
        # Extract file paths
        file_paths = extract_file_paths(input_data.get('tool_input', {}))
        if not file_paths:
            logger.info("No file paths found, exiting")
            print(json.dumps({"suppressOutput": True}))
            return 0
        
        # Load configuration
        start_time = time.time()
        config = load_configuration()
        
        # Apply logging configuration from config file if present
        if 'logging' in config:
            logging_config = config['logging']
            if logging_config.get('enabled', True) is False:
                # Disable all logging
                logger.handlers.clear()
                logger.addHandler(logging.NullHandler())
            elif logging_config.get('level'):
                # Update log level
                new_level = logging_config['level'].upper()
                if new_level in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
                    logger.setLevel(getattr(logging, new_level))
        
        # Get max fix iterations from config (default 3)
        max_fix_iterations = config.get('max_fix_iterations', 3)
        
        # Initialize tracking variables
        all_fix_results: List[Dict[str, Any]] = []
        all_claude_results: List[Dict[str, Any]] = []
        iteration = 0
        results: List[Dict[str, Any]] = []
        lint_time = 0.0
        
        # Iterative fixing loop
        while iteration < max_fix_iterations:
            iteration += 1
            logger.info(f"Starting fix iteration {iteration}/{max_fix_iterations}")
            
            # Lint files in parallel
            if iteration == 1:
                results = lint_files_parallel(file_paths, config)
                lint_time = time.time() - start_time
            else:
                # Re-lint only files that had issues in previous iteration
                files_with_issues = [r['file'] for r in results if not r['success']]
                if not files_with_issues:
                    break  # All issues resolved
                results = lint_files_parallel(files_with_issues, config)
            
            # Check if all files pass
            if all(result.get('success', True) for result in results):
                logger.info(f"All files passed linting on iteration {iteration}")
                break
            
            # Track issues before fixing
            issues_before = sum(len(r.get('issues', [])) for r in results)
            logger.info(f"Iteration {iteration}: {issues_before} issues found")
            
            # Initialize fix_results for this iteration
            fix_results: List[Dict[str, Any]] = []
            
            # Check if we should attempt auto-fix
            if AUTO_FIX_ENABLED and config.get('auto_fix', {}).get('enabled', True) and AutoFixer is not None:
                auto_fixer = AutoFixer()
                
                for result in results:
                    if not result['success'] and result['issues'] and result['linter']:
                        file_path = result['file']
                        linter = result['linter']
                        ext = Path(file_path).suffix
                        
                        if ext in LINTERS and get_fix_command is not None:
                            linter_config = LINTERS[ext]
                            fix_cmd = get_fix_command(linter, linter_config)
                            
                            if fix_cmd and auto_fixer.should_auto_fix(config, linter, result['issues']):
                                fix_result: Dict[str, Any] = auto_fixer.run_auto_fix(file_path, linter, fix_cmd)
                                fix_result['file'] = file_path
                                fix_result['iteration'] = iteration
                                fix_results.append(fix_result)
                                all_fix_results.append(fix_result)
                                
                                # Re-lint the file if it was fixed
                                if fix_result.get('fixed'):
                                    new_result = lint_file(file_path, config)
                                    # Update the result in our list
                                    for i, r in enumerate(results):
                                        if r['file'] == file_path:
                                            results[i] = new_result
                                            break
                
                # Show auto-fix results if any
                if fix_results and iteration == 1 and format_auto_fix_result is not None:  # Only show on first iteration
                    try:
                        print(format_auto_fix_result(fix_results))
                        print()
                    except BrokenPipeError:
                        logger.warning("Broken pipe when printing auto-fix results")
            
            # Check if we should use Claude Code for remaining issues
            # Get current success status after auto-fixes
            current_success = all(result.get('success', True) for result in results)
            
            logger.info(f"Iteration {iteration} - Claude Code enabled: {CLAUDE_CODE_ENABLED}, Current success: {current_success}")
            
            # Initialize claude_results for this iteration
            claude_results: List[Dict[str, Any]] = []
            
            if CLAUDE_CODE_ENABLED and not current_success and ClaudeCodeFixer is not None:
                claude_fixer = ClaudeCodeFixer(config)
                files_to_fix: List[Tuple[str, List[Dict[str, Any]]]] = []
                
                for result in results:
                    if not result['success'] and result['issues']:
                        # Check if we should use Claude for this file
                        auto_fix_failed = any(
                            fr.get('file') == result['file'] and not fr.get('fixed', False)
                            for fr in fix_results
                        )
                        
                        logger.info(f"Checking if Claude should fix {result['file']}: auto_fix_failed={auto_fix_failed}")
                        if claude_fixer.should_use_claude(result['issues'], auto_fix_failed):
                            logger.info(f"Adding {result['file']} to Claude fix list")
                            files_to_fix.append((result['file'], result['issues']))
                
                logger.info(f"Iteration {iteration} - Files to fix with Claude: {len(files_to_fix)}")
                if files_to_fix:
                    if iteration == 1:  # Only show on first iteration
                        try:
                            print("🤖 Attempting to fix remaining issues with Claude Code...")
                        except BrokenPipeError:
                            logger.warning("Broken pipe when printing Claude status")
                    
                    claude_results = claude_fixer.batch_fix_files(files_to_fix)
                    for cr in claude_results:
                        cr['iteration'] = iteration
                    all_claude_results.extend(claude_results)
                    
                    # Re-lint fixed files
                    for claude_result in claude_results:
                        if claude_result.get('success'):
                            files = claude_result.get('files', [claude_result.get('file')])
                            for file_path in files:
                                if file_path:
                                    new_result = lint_file(file_path, config)
                                    # Update the result in our list
                                    for i, r in enumerate(results):
                                        if r['file'] == file_path:
                                            results[i] = new_result
                                            break
                    
                    # Show Claude fix results if any
                    if iteration == 1 and claude_results and format_claude_fix_result is not None:  # Only show on first iteration
                        claude_output = format_claude_fix_result(claude_results)
                        if claude_output:
                            try:
                                print(claude_output)
                                print()
                            except BrokenPipeError:
                                logger.warning("Broken pipe when printing Claude results")
            
            # Check if we made progress
            issues_after = sum(len(r.get('issues', [])) for r in results)
            
            # Check if any fixes were successful in this iteration
            fixes_made = any(fr.get('fixed') for fr in fix_results) if fix_results else False
            claude_fixes_made = any(cr.get('success') for cr in claude_results) if claude_results else False
            
            # Continue if fixes were made, even if issue count increased (e.g., syntax error revealed more issues)
            if not fixes_made and not claude_fixes_made and issues_after >= issues_before:
                logger.info(f"No progress made in iteration {iteration} (before: {issues_before}, after: {issues_after})")
                break
            elif issues_after > issues_before:
                logger.info(f"Issue count increased but fixes were applied in iteration {iteration} (before: {issues_before}, after: {issues_after})")
                # This is OK - fixing syntax errors can reveal more issues
            
            # Check if all issues are resolved
            if all(result.get('success', True) for result in results):
                logger.info(f"All issues resolved after iteration {iteration}")
                break
        
        # Log iteration summary
        if iteration > 1:
            logger.info(f"Completed {iteration} fix iterations")
            try:
                print(f"ℹ️  Completed {iteration} fix iterations")
                if all_claude_results:
                    # Count successful fixes per iteration
                    fixes_by_iteration: Dict[int, int] = {}
                    for cr in all_claude_results:
                        iter_num = cr.get('iteration', 1)
                        if cr.get('success'):
                            fixes_by_iteration[iter_num] = fixes_by_iteration.get(iter_num, 0) + 1
                    
                    if fixes_by_iteration:
                        for iter_num in sorted(fixes_by_iteration.keys()):
                            print(f"   - Iteration {iter_num}: {fixes_by_iteration[iter_num]} file(s) fixed")
                print()
            except BrokenPipeError:
                logger.warning("Broken pipe when printing iteration summary")
        
        # Format final output after all fix attempts
        success, stdout_msg, error_response = format_output(results)
        
        total_time = time.time() - start_time
        logger.info(f"Linter hook completed in {total_time:.2f}s (lint time: {lint_time:.2f}s)")
        
        if success:
            try:
                print(stdout_msg)
                print(json.dumps({"suppressOutput": False}))
            except BrokenPipeError:
                # Handle broken pipe gracefully
                logger.warning("Broken pipe when writing success output")
            return 0
        else:
            # For blocking errors (exit code 2), output to stderr
            # This gets fed back to Claude to help fix the issue
            error_msg: str = error_response.get("reason", "Linting failed") if error_response else "Linting failed"
            try:
                print(error_msg, file=sys.stderr)
                # Also output the JSON response to stdout for Claude Code
                if error_response:
                    print(json.dumps(error_response))
            except BrokenPipeError:
                # Handle broken pipe gracefully
                logger.warning("Broken pipe when writing error output")
            return 2
            
    except BrokenPipeError:
        # Handle broken pipe gracefully - this often happens when output is piped
        logger.warning("Broken pipe error - output stream closed")
        return 0
    except Exception as e:
        # Don't block on unexpected errors
        logger.error(f"Unexpected error in main: {e}", exc_info=True)
        try:
            print(f"⚠ Linter hook error: {str(e)}")
            print(json.dumps({"suppressOutput": False}))
        except BrokenPipeError:
            logger.warning("Broken pipe when writing error output")
        return 0


if __name__ == "__main__":
    sys.exit(main())