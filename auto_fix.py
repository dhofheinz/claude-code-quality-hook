#!/usr/bin/env python3
"""
Auto-fix functionality for the quality hook
Handles automatic fixing of quality issues when supported
"""
import subprocess
import difflib
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
import time

class AutoFixer:
    """Handles automatic fixing of linting issues"""

    def __init__(self, backup_dir: Optional[Path] = None):
        self.backup_dir = backup_dir or Path.home() / '.claude' / 'quality-backups'
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, file_path: str) -> Optional[Path]:
        """Create a backup of the file before fixing"""
        try:
            source = Path(file_path)
            if not source.exists():
                return None

            # Create a unique backup name
            timestamp = int(time.time() * 1000)
            backup_name = f"{source.name}.{timestamp}.bak"
            backup_path = self.backup_dir / backup_name

            shutil.copy2(source, backup_path)
            return backup_path
        except Exception:
            return None

    def run_auto_fix(self, file_path: str, linter: str, fix_cmd: List[str]) -> Dict[str, Any]:
        """Run auto-fix command and return results"""
        # Create backup first
        backup_path = self.create_backup(file_path)

        try:
            # Read original content
            with open(file_path, 'r') as f:
                original_content = f.read()

            # Run the fix command
            result = subprocess.run(
                fix_cmd + [file_path],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Read fixed content
            with open(file_path, 'r') as f:
                fixed_content = f.read()

            # Check if anything changed
            if original_content == fixed_content:
                return {
                    'fixed': False,
                    'message': 'No fixes applied',
                    'backup': str(backup_path) if backup_path else None
                }

            # Generate diff
            diff = list(difflib.unified_diff(
                original_content.splitlines(keepends=True),
                fixed_content.splitlines(keepends=True),
                fromfile=f"{file_path} (original)",
                tofile=f"{file_path} (fixed)",
                n=3
            ))

            return {
                'fixed': True,
                'message': f'Auto-fixed {file_path} with {linter}',
                'diff': ''.join(diff),
                'backup': str(backup_path) if backup_path else None,
                'returncode': result.returncode
            }

        except subprocess.TimeoutExpired:
            # Restore from backup on timeout
            if backup_path and backup_path.exists():
                shutil.copy2(backup_path, file_path)
            return {
                'fixed': False,
                'message': 'Auto-fix timed out',
                'error': 'Timeout after 30 seconds'
            }
        except Exception as e:
            # Restore from backup on error
            if backup_path and backup_path.exists():
                shutil.copy2(backup_path, file_path)
            return {
                'fixed': False,
                'message': 'Auto-fix failed',
                'error': str(e)
            }

    def should_auto_fix(self, config: Dict[str, Any], linter: str, issues: List[Dict[str, Any]]) -> bool:
        """Determine if auto-fix should be attempted"""
        # Check global auto-fix setting
        if not config.get('auto_fix', {}).get('enabled', True):
            return False

        # Check linter-specific setting
        linter_config = config.get('auto_fix', {}).get('linters', {})
        if linter in linter_config and not linter_config[linter]:
            return False

        # Check if we have fixable issues
        fixable_count = sum(1 for issue in issues if issue.get('fixable', True))
        if fixable_count == 0:
            return False

        # Check threshold
        threshold = config.get('auto_fix', {}).get('threshold', 10)
        if len(issues) > threshold:
            return False

        return True

    def restore_backup(self, backup_path: str, original_path: str) -> bool:
        """Restore a file from backup"""
        try:
            backup = Path(backup_path)
            if backup.exists():
                shutil.copy2(backup, original_path)
                return True
        except Exception:
            pass
        return False

    def clean_old_backups(self, max_age_days: int = 7):
        """Clean up old backup files"""
        import time
        current_time = time.time()
        max_age_seconds = max_age_days * 24 * 60 * 60

        for backup_file in self.backup_dir.glob("*.bak"):
            try:
                if current_time - backup_file.stat().st_mtime > max_age_seconds:
                    backup_file.unlink()
            except Exception:
                pass


def get_fix_command(linter: str, linter_config: Dict[str, Any]) -> Optional[List[str]]:
    """Get the fix command for a linter"""
    fix_commands = linter_config.get('fix_commands', {})
    return fix_commands.get(linter)


def format_auto_fix_result(results: List[Dict[str, Any]]) -> str:
    """Format auto-fix results for display"""
    fixed_files: List[str] = []
    failed_files: List[str] = []

    for result in results:
        if result.get('fixed'):
            fixed_files.append(result.get('file', 'unknown'))
        elif result.get('error'):
            failed_files.append(f"{result.get('file', 'unknown')}: {result.get('error')}")

    output: List[str] = []

    if fixed_files:
        output.append(f"✓ Auto-fixed {len(fixed_files)} file(s):")
        for file in fixed_files:
            output.append(f"  - {file}")

    if failed_files:
        output.append(f"✗ Failed to fix {len(failed_files)} file(s):")
        for file in failed_files:
            output.append(f"  - {file}")

    return '\n'.join(output) if output else "No auto-fixes applied"