#!/usr/bin/env python3
"""
Claude Code fixer
"""
import subprocess
import os
import logging
import tempfile
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class IssueCluster:
    """Group of related issues that can be fixed together"""
    issues: List[Dict[str, Any]]
    start_line: int
    end_line: int
    fingerprint: str


class ClaudeCodeFixer:
    """parallel Claude Code fixer"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.claude_config = config.get('claude_code', {})
        self.enabled = self.claude_config.get('enabled', True)
        self.max_workers = self.claude_config.get('max_workers', 10)
        self.timeout = self.claude_config.get('timeout', 600)
        self.logger = logging.getLogger('quality-hook')

        # Prevent infinite loops
        self.max_fix_attempts = self.claude_config.get('max_fix_attempts', 3)
        self._fix_attempts: Dict[str, int] = {}

        # Optimization settings
        self.cluster_distance = self.claude_config.get('cluster_distance', 5)  # Lines apart
        self.max_issues_per_cluster = self.claude_config.get('max_issues_per_cluster', 5)  # Max issues in one cluster
        self.use_memory_git = self.claude_config.get('use_memory_git', True)
        self.batch_similar = self.claude_config.get('batch_similar_issues', True)
        self.predict_simple_fixes = self.claude_config.get('predict_simple_fixes', True)
        
        # Custom issue categories for clustering
        self.custom_categories = self.claude_config.get('custom_issue_categories', {})

        # Git worktree settings
        self.use_git_worktrees = self.claude_config.get('use_git_worktrees', False)
        self.worktree_merge_strategy = self.claude_config.get('worktree_merge_strategy', 'claude')  # Use claude by default
        self.cleanup_worktrees = self.claude_config.get('cleanup_worktrees', True)
        self.max_worktrees = self.claude_config.get('max_worktrees', 10)
        self._active_worktrees: List[str] = []  # Track worktrees for cleanup

        # Pre-compiled fix patterns for common issues
        self.simple_fix_patterns = {
            'F821': {  # Undefined name
                'json': 'import json',
                'datetime': 'from datetime import datetime',
                'logging': 'import logging',
                'os': 'import os',
                'sys': 'import sys',
                'Path': 'from pathlib import Path',
                'List': 'from typing import List',
                'Dict': 'from typing import Dict',
                'Optional': 'from typing import Optional',
            },
            'F841': {  # Local variable assigned but never used
                '_pattern': 'prefix_with_underscore'  # Special pattern
            },
            'E402': {  # Module level import not at top
                '_pattern': 'move_to_top'  # Special pattern
            }
        }

    def should_use_claude(self, issues: List[Dict[str, Any]], auto_fix_failed: bool) -> bool:
        """Determine if we should use Claude Code for fixing"""
        self.logger.info(f"Claude fixer enabled: {self.enabled}")
        if not self.enabled:
            return False

        # Check if claude code is available
        if not self._is_claude_code_available():
            self.logger.info("Claude Code not available")
            return False

        # Use Claude if auto-fix failed or wasn't available
        if auto_fix_failed:
            return True

        # Use Claude for complex issues that auto-fixers can't handle
        complex_patterns = [
            'undefined', 'importerror', 'modulenotfounderror',
            'typeerror', 'nameerror', 'syntax', 'type-error',
            # Pyright/Pylance patterns (lowercase)
            'reportgeneraltypeissues', 'reportargumenttype', 'reportassignmenttype',
            'reportreturntype', 'reportindexissue', 'reportoptionalmemberaccess',
            'reportmissingtypeargument', 'reportpossiblyunboundvariable',
            'reportconstantredefinition', 'reportcallissue', 'reportattributeaccessissue',
            'reportunknownparametertype', 'reportunknownmembertype'
        ]

        for issue in issues:
            message = issue.get('message', '').lower()
            rule = issue.get('rule', '').lower()
            for pattern in complex_patterns:
                if pattern in message or pattern in rule:
                    return True

        return False

    def _is_claude_code_available(self) -> bool:
        """Check if Claude Code CLI is available"""
        try:
            result = subprocess.run(
                ['claude', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def cluster_issues(self, issues: List[Dict[str, Any]]) -> List[IssueCluster]:
        """Group similar issues that can be fixed together"""
        if not self.batch_similar:
            # Each issue is its own cluster
            return [
                IssueCluster(
                    issues=[issue],
                    start_line=issue.get('line', 0),
                    end_line=issue.get('line', 0),
                    fingerprint=self._get_issue_fingerprint(issue)
                )
                for issue in issues
            ]

        # Use advanced clustering strategy if configured
        clustering_strategy = self.claude_config.get('clustering_strategy', 'proximity')
        
        if clustering_strategy == 'similarity':
            return self._cluster_by_similarity(issues)
        elif clustering_strategy == 'hybrid':
            return self._cluster_hybrid(issues)
        else:
            # Default proximity-based clustering
            return self._cluster_by_proximity(issues)

    def _cluster_by_proximity(self, issues: List[Dict[str, Any]]) -> List[IssueCluster]:
        """Original proximity-based clustering"""
        sorted_issues = sorted(issues, key=lambda x: x.get('line', 0))
        clusters: List[IssueCluster] = []
        current_cluster: List[Dict[str, Any]] = []

        for issue in sorted_issues:
            line = issue.get('line', 0)

            if not current_cluster:
                current_cluster.append(issue)
            elif (line - current_cluster[-1].get('line', 0) <= self.cluster_distance and 
                  len(current_cluster) < self.max_issues_per_cluster):
                # Close enough to group together and not too many issues
                current_cluster.append(issue)
            else:
                # Too far or cluster is full, start new cluster
                clusters.append(self._create_cluster(current_cluster))
                current_cluster = [issue]

        if current_cluster:
            clusters.append(self._create_cluster(current_cluster))

        self.logger.info(f"Clustered {len(issues)} issues into {len(clusters)} groups by proximity")
        return clusters

    def _cluster_by_similarity(self, issues: List[Dict[str, Any]]) -> List[IssueCluster]:
        """Cluster issues by type/rule similarity"""
        # Group by issue category
        issue_groups: Dict[str, List[Dict[str, Any]]] = {}
        
        for issue in issues:
            category = self._get_issue_category(issue)
            if category not in issue_groups:
                issue_groups[category] = []
            issue_groups[category].append(issue)
        
        clusters: List[IssueCluster] = []
        
        # Create clusters for each category
        for category, category_issues in issue_groups.items():
            # Sort by line number within category
            sorted_issues = sorted(category_issues, key=lambda x: x.get('line', 0))
            
            # Sub-cluster by proximity within the same category
            current_cluster: List[Dict[str, Any]] = []
            for issue in sorted_issues:
                if not current_cluster:
                    current_cluster.append(issue)
                elif len(current_cluster) < self.max_issues_per_cluster:
                    # Same category and room in cluster
                    current_cluster.append(issue)
                else:
                    # Cluster full, start new one
                    clusters.append(self._create_cluster(current_cluster))
                    current_cluster = [issue]
            
            if current_cluster:
                clusters.append(self._create_cluster(current_cluster))
        
        self.logger.info(f"Clustered {len(issues)} issues into {len(clusters)} groups by similarity")
        return clusters

    def _cluster_hybrid(self, issues: List[Dict[str, Any]]) -> List[IssueCluster]:
        """Hybrid clustering: similar issues that are also nearby"""
        # First group by category
        issue_groups: Dict[str, List[Dict[str, Any]]] = {}
        
        for issue in issues:
            category = self._get_issue_category(issue)
            if category not in issue_groups:
                issue_groups[category] = []
            issue_groups[category].append(issue)
        
        clusters: List[IssueCluster] = []
        
        # Within each category, cluster by proximity
        for category, category_issues in issue_groups.items():
            sorted_issues = sorted(category_issues, key=lambda x: x.get('line', 0))
            current_cluster: List[Dict[str, Any]] = []
            
            for issue in sorted_issues:
                line = issue.get('line', 0)
                
                if not current_cluster:
                    current_cluster.append(issue)
                elif (line - current_cluster[-1].get('line', 0) <= self.cluster_distance and 
                      len(current_cluster) < self.max_issues_per_cluster):
                    # Same category, close proximity, and room in cluster
                    current_cluster.append(issue)
                else:
                    # Too far or cluster full
                    clusters.append(self._create_cluster(current_cluster))
                    current_cluster = [issue]
            
            if current_cluster:
                clusters.append(self._create_cluster(current_cluster))
        
        self.logger.info(f"Clustered {len(issues)} issues into {len(clusters)} groups using hybrid strategy")
        return clusters

    def _get_issue_category(self, issue: Dict[str, Any]) -> str:
        """Categorize an issue for similarity grouping"""
        rule = issue.get('rule', '').lower()
        message = issue.get('message', '').lower()
        
        # Check custom categories first
        for category_name, patterns in self.custom_categories.items():
            if isinstance(patterns, list):
                for pattern in patterns:
                    if isinstance(pattern, str) and (pattern.lower() in rule or pattern.lower() in message):
                        return category_name
        
        # Import-related issues
        if any(keyword in rule or keyword in message for keyword in ['import', 'f401', 'e402', 'isort']):
            return 'imports'
        
        # Type-related issues
        if any(keyword in rule or keyword in message for keyword in [
            'type', 'reportargumenttype', 'reportassignmenttype', 'reportreturntype',
            'reportmissingtypeargument', 'annotation', 'typing'
        ]):
            return 'types'
        
        # Undefined names
        if any(keyword in rule or keyword in message for keyword in ['f821', 'undefined', 'nameerror', 'unbound']):
            return 'undefined'
        
        # Unused variables
        if any(keyword in rule or keyword in message for keyword in ['f841', 'unused', 'assigned but never used']):
            return 'unused'
        
        # Docstring issues
        if any(keyword in rule or keyword in message for keyword in ['d', 'docstring', 'missing docstring', 'd100', 'd101', 'd102']):
            return 'docstrings'
        
        # Syntax and formatting
        if any(keyword in rule or keyword in message for keyword in ['syntax', 'indent', 'whitespace', 'format', 'e1', 'e2', 'e3', 'w']):
            return 'formatting'
        
        # Security issues
        if any(keyword in rule or keyword in message for keyword in ['s', 'security', 'bandit', 'unsafe']):
            return 'security'
        
        # Complexity issues
        if any(keyword in rule or keyword in message for keyword in ['c901', 'complex', 'cyclomatic', 'mccabe']):
            return 'complexity'
        
        # Default category based on rule prefix
        if rule:
            prefix = rule[0].lower() if rule else 'other'
            return f'rule_{prefix}'
        
        return 'other'

    def _create_cluster(self, issues: List[Dict[str, Any]]) -> IssueCluster:
        """Create a cluster from a list of issues"""
        lines: List[int] = [i.get('line', 0) for i in issues]
        return IssueCluster(
            issues=issues,
            start_line=min(lines),
            end_line=max(lines),
            fingerprint=self._get_cluster_fingerprint(issues)
        )

    def _get_issue_fingerprint(self, issue: Dict[str, Any]) -> str:
        """Get unique fingerprint for an issue"""
        return f"{issue.get('rule', '')}:{issue.get('line', 0)}"

    def _get_cluster_fingerprint(self, issues: List[Dict[str, Any]]) -> str:
        """Get unique fingerprint for a cluster"""
        fingerprints = [self._get_issue_fingerprint(i) for i in issues]
        return hashlib.md5('|'.join(fingerprints).encode()).hexdigest()[:8]

    def predict_simple_fix(self, issue: Dict[str, Any], file_content: str) -> Optional[str]:
        """Try to predict fix for simple issues without calling Claude"""
        if not self.predict_simple_fixes:
            return None

        rule = issue.get('rule', '')
        message = issue.get('message', '')
        self.logger.debug(f"Trying to predict fix for rule={rule}, message={message}")

        # Handle undefined names
        if rule == 'F821' and rule in self.simple_fix_patterns:
            # Extract the undefined name from message
            if "Undefined name `" in message:
                name: str = message.split("`")[1]
                if name in self.simple_fix_patterns['F821']:
                    import_stmt = self.simple_fix_patterns['F821'][name]
                    # Check if import already exists
                    if import_stmt not in file_content:
                        self.logger.info(f"Predicted fix for {rule}: {import_stmt}")
                        return self._apply_import_fix(file_content, import_stmt)

        # Handle unused variables
        elif rule == 'F841':
            line_num: int = issue.get('line', 0) - 1
            lines = file_content.split('\n')
            if 0 <= line_num < len(lines):
                line: str = lines[line_num]
                # Simple pattern: prefix variable with underscore
                if ' = ' in line:
                    var_name: str = line.split('=')[0].strip()
                    if not var_name.startswith('_'):
                        lines[line_num] = line.replace(var_name, f'_{var_name}', 1)
                        self.logger.info(f"Predicted fix for {rule}: prefix with underscore")
                        return '\n'.join(lines)

        return None

    def _apply_import_fix(self, content: str, import_stmt: str) -> str:
        """Apply import statement at the correct location"""
        lines = content.split('\n')

        # Find where to insert import
        insert_pos = 0
        in_docstring = False
        docstring_char = None

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Handle docstrings
            if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
                docstring_char = '"""' if stripped.startswith('"""') else "'''"
                in_docstring = True
                if stripped.endswith(docstring_char) and len(stripped) > 3:
                    in_docstring = False
                continue
            elif in_docstring and docstring_char and stripped.endswith(docstring_char):
                in_docstring = False
                insert_pos = i + 1
                continue

            # Skip comments and empty lines at start
            if not in_docstring and stripped and not stripped.startswith('#'):
                # Found first code line
                if stripped.startswith('import ') or stripped.startswith('from '):
                    # Insert after existing imports
                    insert_pos = i + 1
                    while insert_pos < len(lines) and (
                        lines[insert_pos].strip().startswith('import ') or
                        lines[insert_pos].strip().startswith('from ') or
                        not lines[insert_pos].strip()
                    ):
                        insert_pos += 1
                else:
                    # Insert before first code line
                    insert_pos = i
                break

        lines.insert(insert_pos, import_stmt)
        return '\n'.join(lines)

    def create_minimal_patch(self, original: str, fixed: str) -> str:
        """Create minimal patch for the fix"""
        # Use git diff algorithm for minimal patch
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f1:
            f1.write(original)
            f1.flush()

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f2:
                f2.write(fixed)
                f2.flush()

                result = subprocess.run(
                    ['git', 'diff', '--no-index', '--minimal', f1.name, f2.name],
                    capture_output=True,
                    text=True
                )

                os.unlink(f1.name)
                os.unlink(f2.name)

                return result.stdout

    def apply_patch_in_memory(self, content: str, patch: str) -> str:
        """Apply patch to content in memory"""
        # For now, use the full fixed content
        # TODO: Implement proper patch application
        return patch

    def fix_cluster_with_worktree(self, file_path: str, cluster: IssueCluster,
                                  base_path: str, predicted_fixes: Optional[List[Tuple[Dict[str, Any], str]]] = None) -> Dict[str, Any]:
        """Fix a cluster of issues in its own git worktree"""
        worktree_path = self._create_worktree_for_cluster(base_path, cluster)
        if not worktree_path:
            return {
                'success': False,
                'cluster': cluster,
                'error': 'Failed to create worktree'
            }

        try:
            # Get relative path from base
            rel_path = Path(file_path).relative_to(base_path)
            worktree_file = Path(worktree_path) / rel_path

            # Ensure the file exists in the worktree
            if not worktree_file.exists():
                self.logger.error(f"File {worktree_file} not found in worktree")
                # Clean up the worktree before returning
                self._cleanup_worktree(worktree_path)
                return {
                    'success': False,
                    'cluster': cluster,
                    'error': f'File not found in worktree: {rel_path}'
                }

            # Read the content from worktree
            worktree_content = worktree_file.read_text()

            # Apply predicted fixes to the worktree file first
            if predicted_fixes:
                # Apply each predicted fix sequentially
                for _, fixed_content in predicted_fixes:
                    # The fixed_content is the full file content after that fix
                    worktree_content = fixed_content
                # Write the predicted fixes to the worktree
                worktree_file.write_text(worktree_content)
                # Stage the changes in the worktree
                subprocess.run(
                    ['git', 'add', str(rel_path)],
                    cwd=worktree_path,
                    capture_output=True
                )

            # Run Claude on the worktree copy
            result = self.fix_cluster_with_claude(
                str(worktree_file),
                cluster,
                worktree_content
            )

            if result['success']:
                # Create a patch from the worktree
                patch_result = subprocess.run(
                    ['git', 'diff', 'HEAD', str(rel_path)],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True
                )

                result['patch'] = patch_result.stdout
                result['worktree_path'] = worktree_path
                result['rel_path'] = str(rel_path)
                self.logger.info(f"Created patch for cluster {cluster.fingerprint}, size: {len(result['patch'])} bytes")

            return result

        except Exception as e:
            self.logger.error(f"Error in worktree fix: {e}")
            # Clean up the worktree on error
            if worktree_path:
                self._cleanup_worktree(worktree_path)
            return {
                'success': False,
                'cluster': cluster,
                'error': str(e)
            }
        finally:
            # Don't cleanup here for successful cases, we'll do it after merging
            pass

    def fix_cluster_with_claude(self, file_path: str, cluster: IssueCluster,
                               file_content: str) -> Dict[str, Any]:
        """Fix a cluster of issues with Claude"""
        try:
            # Create focused prompt for the cluster
            prompt = self._create_cluster_prompt(file_path, cluster, file_content)

            # Run Claude
            cmd = [
                'claude',
                '-p',
                prompt,
                '--dangerously-skip-permissions',
                '--allowedTools', 'Read,Edit,MultiEdit',
                '--output-format', 'text'
            ]

            # Set environment variable to prevent hook cascading
            env = os.environ.copy()
            env['CLAUDE_CODE_FIX_IN_PROGRESS'] = '1'

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=Path(file_path).parent,
                env=env
            )

            if result.returncode == 0:
                # Read the fixed file
                fixed_content = Path(file_path).read_text()

                return {
                    'success': True,
                    'fixed_content': fixed_content,
                    'cluster': cluster
                }
            else:
                return {
                    'success': False,
                    'cluster': cluster,
                    'error': result.stderr or result.stdout
                }

        except Exception as e:
            self.logger.error(f"Failed to fix cluster: {e}")
            return {
                'success': False,
                'cluster': cluster,
                'error': str(e)
            }

    def _extract_context(self, content: str, start_line: int, end_line: int,
                        context_lines: int = 3) -> str:
        """Extract code context around the issue"""
        lines = content.split('\n')
        start = max(0, start_line - context_lines - 1)
        end = min(len(lines), end_line + context_lines)
        return '\n'.join(lines[start:end])

    def _create_cluster_prompt(self, file_path: str, cluster: IssueCluster,
                              content: str) -> str:
        """Create optimized prompt for a cluster of issues"""
        # Handle both regular paths and worktree paths
        try:
            relative_path = Path(file_path).relative_to(Path.cwd())
        except ValueError:
            # If file_path is in a worktree, extract just the filename
            # This happens when Claude is running in a worktree directory
            relative_path = Path(file_path).name

        prompt = f"""Fix the following {len(cluster.issues)} linting issues in {relative_path}:

"""

        for issue in cluster.issues:
            prompt += f"Line {issue.get('line', 0)}: [{issue.get('rule', '')}] {issue.get('message', '')}\n"

        prompt += """

Requirements:
- Fix ONLY the issues listed above
- Maintain code style and functionality
- Make minimal changes
- Consider the full file context when making fixes"""

        return prompt

    def batch_fix_files(self, file_issues: List[Tuple[str, List[Dict[str, Any]]]]) -> List[Dict[str, Any]]:
        """Fix multiple files using ultra-optimized approach"""
        results: List[Dict[str, Any]] = []

        try:
            # Process each file
            for file_path, issues in file_issues:
                result = self._fix_single_file(file_path, issues)
                result['file'] = file_path
                results.append(result)
        finally:
            # Always clean up any remaining worktrees
            if self.cleanup_worktrees:
                self.cleanup_all_worktrees()

        return results

    def _fix_single_file(self, file_path: str, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Fix a single file using ultra-optimized parallel approach"""
        self.logger.info(f"_fix_single_file called for {file_path} with {len(issues)} issues")

        # Check fix attempts to prevent infinite loops
        if file_path not in self._fix_attempts:
            self._fix_attempts[file_path] = 0

        self._fix_attempts[file_path] += 1
        if self._fix_attempts[file_path] > self.max_fix_attempts:
            self.logger.warning(f"Max fix attempts ({self.max_fix_attempts}) reached for {file_path}")
            return {
                'success': False,
                'error': f'Max fix attempts ({self.max_fix_attempts}) exceeded',
                'message': 'Unable to fix all issues after multiple attempts'
            }

        try:
            # Read file once
            file_content = Path(file_path).read_text()
            original_content = file_content
            self.logger.info(f"Read file, content length: {len(file_content)}")

            # Try simple predictions first
            predicted_fixes: List[Tuple[Dict[str, Any], str]] = []
            remaining_issues: List[Dict[str, Any]] = []
            git_root = None  # Initialize here for scope
            cluster_results: List[Dict[str, Any]] = []  # Initialize here for scope

            for issue in issues:
                predicted = self.predict_simple_fix(issue, file_content)
                if predicted:
                    predicted_fixes.append((issue, predicted))
                    file_content = predicted  # Apply incrementally
                else:
                    remaining_issues.append(issue)

            self.logger.info(f"Predicted {len(predicted_fixes)} simple fixes, "
                           f"{len(remaining_issues)} need Claude")

            clusters: List[IssueCluster] = []  # Initialize clusters
            if remaining_issues:
                # Cluster remaining issues
                clusters = self.cluster_issues(remaining_issues)

                # Check if we should use git worktrees
                git_root = self._get_git_root() if self.use_git_worktrees else None

                # Process clusters in parallel
                with ThreadPoolExecutor(max_workers=min(self.max_workers, len(clusters))) as executor:
                    if self.use_git_worktrees and git_root:
                        # Use git worktrees for true parallel processing
                        # First ensure the file is in the index
                        rel_path = Path(file_path).relative_to(git_root)

                        # Add the file to git index if it exists but isn't tracked
                        if Path(file_path).exists():
                            subprocess.run(
                                ['git', 'add', '-N', str(rel_path)],  # -N adds with intent to add
                                cwd=git_root,
                                capture_output=True
                            )

                        futures: List[Any] = []
                        for cluster in clusters[:self.max_worktrees]:  # Limit worktrees
                            future = executor.submit(
                                self.fix_cluster_with_worktree,
                                file_path, cluster, git_root, predicted_fixes
                            )
                            futures.append(future)

                        # Collect results
                        all_worktree_results: List[Dict[str, Any]] = []  # Track all results for cleanup
                        for future in as_completed(futures):
                            try:
                                result = future.result()
                                all_worktree_results.append(result)
                                if result['success']:
                                    cluster_results.append(result)
                            except Exception as e:
                                self.logger.error(f"Worktree fix failed: {e}")

                        # Define cleanup function
                        def cleanup_all():
                            for result in all_worktree_results:
                                if 'worktree_path' in result:
                                    self._cleanup_worktree(result['worktree_path'])

                        # Merge all fixes using git
                        if cluster_results:
                            merge_success = self._merge_worktree_fixes(
                                git_root, file_path, cluster_results
                            )

                            # Clean up worktrees after merge
                            if self.cleanup_worktrees:
                                cleanup_all()

                            if merge_success:
                                # Read the merged content
                                file_content = Path(file_path).read_text()
                            else:
                                self.logger.error("Failed to merge worktree fixes")
                                # Clean up worktrees on merge failure too
                                if self.cleanup_worktrees:
                                    cleanup_all()
                                return {
                                    'success': False,
                                    'error': 'Failed to merge worktree fixes'
                                }
                        else:
                            # No successful results, but still clean up worktrees
                            if self.cleanup_worktrees:
                                cleanup_all()
                    else:
                        # Use original in-memory approach
                        futures: List[Any] = []
                        for cluster in clusters:
                            # Each cluster gets a fresh copy of the file
                            future = executor.submit(
                                self.fix_cluster_with_claude,
                                file_path, cluster, file_content
                            )
                            futures.append(future)

                        # Collect results and merge
                        cluster_fixes: List[Dict[str, Any]] = []
                        for future in as_completed(futures):
                            result = future.result()
                            if result['success']:
                                cluster_fixes.append(result)

                        # Apply all fixes
                        if cluster_fixes:
                            file_content = self._merge_cluster_fixes(
                                original_content, file_content, cluster_fixes
                            )

            # Write final result
            if file_content != original_content:
                Path(file_path).write_text(file_content)
                if self.use_git_worktrees and git_root and remaining_issues:
                    return {
                        'success': True,
                        'message': f"Fixed {len(issues)} issues with {len(predicted_fixes)} "
                                  f"predictions and {len(cluster_results)} worktree fixes",
                        'predicted': len(predicted_fixes),
                        'worktrees_used': len(cluster_results),
                        'claude_calls': len(cluster_results)
                    }
                else:
                    return {
                        'success': True,
                        'message': f"Fixed {len(issues)} issues with {len(predicted_fixes)} "
                                  f"predictions and {len(clusters) if remaining_issues else 0} Claude calls",
                        'predicted': len(predicted_fixes),
                        'claude_calls': len(clusters) if remaining_issues else 0
                    }

            return {
                'success': False,
                'message': 'No changes made'
            }

        except Exception as e:
            self.logger.error(f"Ultra fix failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _merge_worktree_fixes(self, base_path: str, file_path: str,
                            cluster_results: List[Dict[str, Any]]) -> bool:
        """Intelligently merge fixes from multiple worktrees using Claude"""
        if not cluster_results:
            return True

        # Sort by cluster position to apply in order
        sorted_results = sorted(
            cluster_results,
            key=lambda r: r['cluster'].start_line
        )

        # rel_path would be used for logging or git operations
        # _rel_path = Path(file_path).relative_to(base_path)

        if self.worktree_merge_strategy == 'claude':
            # Use Claude to intelligently merge all fixes
            return self._merge_with_claude(base_path, file_path, sorted_results)

        elif self.worktree_merge_strategy == 'sequential':
            # Apply patches sequentially
            for result in sorted_results:
                if result.get('patch'):
                    # Apply the patch
                    apply_result = subprocess.run(
                        ['git', 'apply', '--3way', '--whitespace=fix'],
                        input=result['patch'],
                        text=True,
                        cwd=base_path,
                        capture_output=True
                    )

                    if apply_result.returncode != 0:
                        self.logger.warning(
                            f"Failed to apply patch for cluster {result['cluster'].fingerprint}: "
                            f"{apply_result.stderr}"
                        )
                        # Try Claude merge as fallback
                        self.logger.info("Falling back to Claude merge strategy")
                        return self._merge_with_claude(base_path, file_path, sorted_results)

                    self.logger.info(f"Applied patch for cluster {result['cluster'].fingerprint}")

        elif self.worktree_merge_strategy == 'octopus':
            # Create branches for each fix and merge them together
            branches_to_merge: List[str] = []

            for _, result in enumerate(sorted_results):
                if result.get('patch'):
                    branch_name = f"linter-fix-{result['cluster'].fingerprint}"

                    # Create a branch in the worktree
                    subprocess.run(
                        ['git', 'checkout', '-b', branch_name],
                        cwd=result['worktree_path'],
                        capture_output=True
                    )

                    # Stage and commit the changes
                    subprocess.run(
                        ['git', 'add', str(result['rel_path'])],
                        cwd=result['worktree_path'],
                        capture_output=True
                    )

                    subprocess.run(
                        ['git', 'commit', '-m', f"Fix cluster {result['cluster'].fingerprint}"],
                        cwd=result['worktree_path'],
                        capture_output=True
                    )

                    branches_to_merge.append(branch_name)

            # Perform octopus merge
            if branches_to_merge:
                merge_cmd = ['git', 'merge', '--no-ff', '-m', 'Merge linter fixes'] + branches_to_merge
                merge_result = subprocess.run(
                    merge_cmd,
                    cwd=base_path,
                    capture_output=True,
                    text=True
                )

                if merge_result.returncode != 0:
                    self.logger.error(f"Octopus merge failed: {merge_result.stderr}")
                    return False

        return True

    def _merge_with_claude(self, base_path: str, file_path: str,
                          cluster_results: List[Dict[str, Any]]) -> bool:
        """Use Claude to intelligently merge fixes from multiple worktrees"""
        try:
            # Read the current file content
            current_content = Path(file_path).read_text()

            # Collect all the fixed versions from worktrees
            fixed_versions: List[Dict[str, Any]] = []
            for result in cluster_results:
                if result.get('success') and 'worktree_path' in result:
                    worktree_file = Path(result['worktree_path']) / result['rel_path']
                    if worktree_file.exists():
                        fixed_content = worktree_file.read_text()
                        fixed_versions.append({
                            'cluster': result['cluster'],
                            'content': fixed_content,
                            'issues': result['cluster'].issues
                        })

            if not fixed_versions:
                self.logger.warning("No fixed versions found to merge")
                return False

            # Create a comprehensive prompt for Claude
            prompt = self._create_merge_prompt(file_path, current_content, fixed_versions)

            # Run Claude in non-interactive mode to merge
            cmd = [
                'claude',
                '-p',
                prompt,
                '--dangerously-skip-permissions',
                '--allowedTools', 'Read,Write',
                '--output-format', 'text'
            ]

            # Set environment variable to prevent hook cascading
            env = os.environ.copy()
            env['CLAUDE_CODE_FIX_IN_PROGRESS'] = '1'

            self.logger.info(f"Using Claude to merge {len(fixed_versions)} versions")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=base_path,
                env=env
            )

            if result.returncode == 0:
                self.logger.info("Claude successfully merged all fixes")
                return True
            else:
                self.logger.error(f"Claude merge failed: {result.stderr or result.stdout}")
                return False

        except Exception as e:
            self.logger.error(f"Error in Claude merge: {e}")
            return False

    def _create_merge_prompt(self, file_path: str, current_content: str,
                            fixed_versions: List[Dict[str, Any]]) -> str:
        """Create a prompt for Claude to merge multiple fixed versions"""
        filename = Path(file_path).name

        prompt = f"""You are tasked with merging multiple fixes for a Python file that has various linting issues.

The file {filename} had multiple linting issues that were fixed in parallel by different instances.
Your job is to intelligently merge all these fixes into a single, coherent file.

IMPORTANT REQUIREMENTS:
1. The final merged file must include ALL fixes from ALL versions
2. Resolve any conflicts by choosing the most complete fix
3. Ensure no fixes are lost in the merge
4. Maintain code functionality and style
5. The merged result should pass all linting checks

Here are the issues that were fixed in each version:

"""

        for i, version in enumerate(fixed_versions, 1):
            prompt += f"\nVersion {i} fixed these issues:\n"
            for issue in version['issues']:
                prompt += f"  - Line {issue.get('line', 0)}: [{issue.get('rule', '')}] {issue.get('message', '')}\n"

        prompt += f"""\n\nThe current file is at {file_path}.

MERGE STRATEGY:
1. Read the current file to understand the base state
2. Analyze each fix to understand what was changed
3. Apply all fixes, ensuring no fix overwrites another
4. If fixes conflict, choose the most comprehensive solution
5. Write the final merged result back to {file_path}

Proceed with the merge."""

        return prompt

    def _merge_cluster_fixes(self, original: str, current: str,
                           cluster_fixes: List[Dict[str, Any]]) -> str:
        """Merge fixes from multiple clusters (non-worktree mode)"""
        # For non-worktree mode, use the last successful fix
        if cluster_fixes:
            return cluster_fixes[-1]['fixed_content']
        return current

    @lru_cache(maxsize=1000)
    def _is_import_line(self, line: str) -> bool:
        """Check if a line is an import statement (cached)"""
        stripped = line.strip()
        return stripped.startswith('import ') or stripped.startswith('from ')

    def _get_git_root(self) -> Optional[str]:
        """Get the git repository root"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            self.logger.warning("Not in a git repository")
            return None

    def _create_worktree_for_cluster(self, base_path: str, cluster: IssueCluster) -> Optional[str]:
        """Create a git worktree for parallel processing"""
        try:
            # Generate unique worktree name
            worktree_name = f"linter-fix-{cluster.fingerprint}-{uuid.uuid4().hex[:8]}"
            # Use .claude directory in the repo for worktrees
            claude_dir = Path(base_path) / '.claude' / 'worktrees'
            worktree_path = claude_dir / worktree_name

            # Ensure parent directory exists
            worktree_path.parent.mkdir(parents=True, exist_ok=True)

            # Create worktree
            cmd = ['git', 'worktree', 'add', '--detach', str(worktree_path)]
            result = subprocess.run(
                cmd,
                cwd=base_path,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                self.logger.error(f"Failed to create worktree: {result.stderr}")
                return None

            self._active_worktrees.append(str(worktree_path))
            self.logger.info(f"Created worktree at {worktree_path}")
            return str(worktree_path)

        except Exception as e:
            self.logger.error(f"Error creating worktree: {e}")
            return None

    def _cleanup_worktree(self, worktree_path: str):
        """Remove a git worktree after use"""
        try:
            if worktree_path in self._active_worktrees:
                self._active_worktrees.remove(worktree_path)

            # Force remove the worktree
            subprocess.run(
                ['git', 'worktree', 'remove', '--force', worktree_path],
                capture_output=True
            )

            # Also try to remove the directory if it still exists
            if Path(worktree_path).exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

            self.logger.debug(f"Cleaned up worktree: {worktree_path}")

        except Exception as e:
            self.logger.warning(f"Error cleaning up worktree {worktree_path}: {e}")

    def cleanup_all_worktrees(self):
        """Clean up all active worktrees"""
        for worktree in list(self._active_worktrees):
            self._cleanup_worktree(worktree)
        self._active_worktrees.clear()


def format_claude_fix_result(results: List[Dict[str, Any]]) -> str:
    """Format Claude Code fix results for display"""
    success_count = sum(1 for r in results if r.get('success'))
    fail_count = len(results) - success_count

    output: List[str] = []

    if success_count > 0:
        output.append(f"🤖 Claude Code fixed {success_count} file(s)")

    if fail_count > 0:
        output.append(f"⚠️  Claude Code failed to fix {fail_count} file(s)")
        for result in results:
            if not result.get('success'):
                file = result.get('file', 'unknown')
                error = result.get('error', 'Unknown error')
                output.append(f"  - {file}: {error}")

    return '\n'.join(output) if output else ""