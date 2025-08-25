#!/usr/bin/env python3
"""
nobifinder.py - Find all Kotlin/Java files that use a given class or its members

A single-file Python tool that provides an interactive CLI to search for usage
of a specific Kotlin/Java class, its methods, or its fields/properties across 
a codebase. Respects .gitignore rules and provides both human-readable and JSON 
output formats with optional editor integration.

Usage Examples:
    python nobifinder.py
    python nobifinder.py --mode method --member "doSomething,helper"
    python nobifinder.py --mode field --member "/^id.*/" --json --with-lines
    python nobifinder.py --root /path/to/project --open
    python nobifinder.py --select --strict-import --same-package-ok
    python nobifinder.py --self-test

To make executable:
    chmod +x nobifinder.py && ./nobifinder.py

Dependencies:
    - pathspec (install with: pip install pathspec)
    - If pathspec is not available, .gitignore handling will be disabled

Limitations:
    - Uses heuristics only, no full AST parsing
    - Generic/common class names may cause false positives
    - Does not detect reflection/dynamic loading/code generation
    - Multi-module Gradle source sets discovered only by directory walk
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Pattern, Set, Tuple

# Try to import pathspec for gitignore handling
try:
    import pathspec
    HAS_PATHSPEC = True
except ImportError:
    HAS_PATHSPEC = False


class GitignoreMatcher:
    """Handles loading and matching against .gitignore patterns."""
    
    def __init__(self, root: Path, follow_symlinks: bool = False):
        self.root = root
        self.follow_symlinks = follow_symlinks
        self.spec = None
        self.always_ignore = {
            '.git', 'build', 'out', 'dist', 'target', '.gradle', '.idea', 'node_modules'
        }
        
        if HAS_PATHSPEC:
            self._load_gitignore_patterns()
    
    def _load_gitignore_patterns(self):
        """Load and merge .gitignore patterns from root and nested directories."""
        patterns = []
        
        # Walk through the directory tree to collect all .gitignore files
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=self.follow_symlinks):
            # Skip always-ignored directories
            dirnames[:] = [d for d in dirnames if d not in self.always_ignore]
            
            gitignore_path = Path(dirpath) / '.gitignore'
            if gitignore_path.is_file():
                try:
                    with open(gitignore_path, 'r', encoding='utf-8', errors='ignore') as f:
                        patterns.extend(f.read().splitlines())
                except (OSError, IOError):
                    continue
        
        if patterns:
            self.spec = pathspec.PathSpec.from_lines('gitwildmatch', patterns)
    
    def is_ignored(self, path: Path) -> bool:
        """Check if a path should be ignored."""
        # Always ignore common junk directories
        parts = path.parts
        if any(part in self.always_ignore for part in parts):
            return True
        
        if not HAS_PATHSPEC or self.spec is None:
            return False
        
        # Convert to relative path from root for pathspec matching
        try:
            rel_path = path.relative_to(self.root)
            return self.spec.match_file(str(rel_path))
        except ValueError:
            return False


def parse_target_metadata(path: Path) -> Tuple[str, str, str]:
    """
    Parse target file to extract package, class name, and FQN.
    Returns (package, class_name, fqn).
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except (OSError, IOError) as e:
        raise ValueError(f"Cannot read target file: {e}")
    
    # Extract package
    package = ""
    package_match = re.search(r'^\s*package\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s*;?\s*$', content, re.MULTILINE)
    if package_match:
        package = package_match.group(1)
    
    # Extract class/interface/enum declarations
    class_patterns = [
        r'^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?(?:abstract\s+|final\s+|open\s+)?(?:data\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        r'^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?interface\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        r'^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?enum\s+(?:class\s+)?([a-zA-Z_][a-zA-Z0-9_]*)',
        r'^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?(?:sealed\s+)?(?:data\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)',
        r'^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?annotation\s+class\s+([a-zA-Z_][a-zA-Z0-9_]*)',
    ]
    
    class_names = []
    for pattern in class_patterns:
        matches = re.finditer(pattern, content, re.MULTILINE)
        for match in matches:
            class_names.append(match.group(1))
    
    if not class_names:
        raise ValueError("No class/interface/enum declarations found in target file")
    
    # Prefer class matching filename, otherwise use first
    filename_stem = path.stem
    class_name = next((name for name in class_names if name == filename_stem), class_names[0])
    
    # Construct FQN
    fqn = f"{package}.{class_name}" if package else class_name
    
    return package, class_name, fqn


def parse_target_members(content: str, class_name: str) -> Dict[str, List[str]]:
    """
    Parse target file content to extract class members.
    Returns {'fields': [...], 'methods': [...]}
    """
    fields = set()
    methods = set()
    
    # Remove comments and strings for cleaner parsing
    clean_content = strip_comments_and_strings(content)
    
    # Find the class definition to work within its scope
    class_pattern = rf'(?:data\s+)?class\s+{re.escape(class_name)}\s*(?:\([^)]*\))?\s*(?:\:\s*[^{{]*)?{{'
    class_match = re.search(class_pattern, clean_content, re.MULTILINE | re.DOTALL)
    
    if class_match:
        class_start = class_match.start()
        # Find the end of the class (simplified - just find the next top-level declaration or end of file)
        remaining_content = clean_content[class_start:]
        
        # Extract primary constructor parameters (Kotlin data class)
        primary_constructor_match = re.search(rf'class\s+{re.escape(class_name)}\s*\(([^)]*)\)', remaining_content)
        if primary_constructor_match:
            params = primary_constructor_match.group(1)
            # Parse val/var parameters
            param_pattern = r'(?:val|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*[^,)]*'
            for match in re.finditer(param_pattern, params):
                fields.add(match.group(1))
    
    # Find all field/property declarations
    field_patterns = [
        # Kotlin properties
        r'^\s*(?:val|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]',
        # Java fields (simplified)
        r'^\s*(?:public|private|protected)?\s*(?:static)?\s*(?:final)?\s*[a-zA-Z_][a-zA-Z0-9_<>,\s]*\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[;=]',
    ]
    
    for pattern in field_patterns:
        for match in re.finditer(pattern, clean_content, re.MULTILINE):
            field_name = match.group(1)
            # Skip common non-field names
            if field_name not in {'class', 'interface', 'enum', 'fun', 'val', 'var'}:
                fields.add(field_name)
    
    # Find all method declarations
    method_patterns = [
        # Kotlin functions
        r'^\s*(?:override\s+)?(?:suspend\s+)?fun\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
        # Java methods (simplified)
        r'^\s*(?:public|private|protected)?\s*(?:static)?\s*(?:final)?\s*(?:synchronized)?\s*[a-zA-Z_][a-zA-Z0-9_<>,\s]*\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',
    ]
    
    for pattern in method_patterns:
        for match in re.finditer(pattern, clean_content, re.MULTILINE):
            method_name = match.group(1)
            # Skip constructors and common keywords
            if method_name not in {class_name, 'class', 'interface', 'enum', 'if', 'for', 'while', 'when'}:
                methods.add(method_name)
    
    return {
        'fields': sorted(list(fields)),
        'methods': sorted(list(methods))
    }


def strip_comments_and_strings(code: str) -> str:
    """
    Remove comments and string literals from Java/Kotlin code.
    This is a lightweight implementation, not a full parser.
    """
    result = []
    i = 0
    length = len(code)
    
    while i < length:
        # Single-line comment
        if i < length - 1 and code[i:i+2] == '//':
            # Skip to end of line
            while i < length and code[i] != '\n':
                i += 1
            if i < length:
                result.append('\n')  # Preserve line breaks
                i += 1
        # Multi-line comment
        elif i < length - 1 and code[i:i+2] == '/*':
            i += 2
            # Skip to end of comment
            while i < length - 1:
                if code[i:i+2] == '*/':
                    i += 2
                    break
                # Preserve line breaks in comments
                if code[i] == '\n':
                    result.append('\n')
                i += 1
        # String literal (double quotes)
        elif code[i] == '"':
            result.append(' ')  # Replace string with space
            i += 1
            while i < length:
                if code[i] == '"':
                    i += 1
                    break
                elif code[i] == '\\' and i < length - 1:
                    i += 2  # Skip escaped character
                else:
                    i += 1
        # String literal (single quotes) - for Kotlin chars
        elif code[i] == "'":
            result.append(' ')  # Replace string with space
            i += 1
            while i < length:
                if code[i] == "'":
                    i += 1
                    break
                elif code[i] == '\\' and i < length - 1:
                    i += 2  # Skip escaped character
                else:
                    i += 1
        else:
            result.append(code[i])
            i += 1
    
    return ''.join(result)


def build_patterns(fqn: str, class_name: str) -> Dict[str, Pattern]:
    """Build regex patterns for detecting class usage."""
    patterns = {}
    
    # Import patterns
    patterns['import_fqn'] = re.compile(rf'\bimport\s+{re.escape(fqn)}\b')
    patterns['import_class'] = re.compile(rf'\bimport\s+[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*\.{re.escape(class_name)}\b')
    
    # Direct FQN usage
    patterns['direct_fqn'] = re.compile(rf'\b{re.escape(fqn)}\b')
    
    # Simple name usage patterns
    patterns['constructor'] = re.compile(rf'\b{re.escape(class_name)}\s*\(')
    patterns['type_annotation'] = re.compile(rf':\s*{re.escape(class_name)}\b')
    patterns['generic'] = re.compile(rf'<[^<>]*\b{re.escape(class_name)}\b[^<>]*>')
    patterns['annotation'] = re.compile(rf'@{re.escape(class_name)}\b')
    patterns['instanceof'] = re.compile(rf'\bis\s+{re.escape(class_name)}\b')
    patterns['simple_name'] = re.compile(rf'\b{re.escape(class_name)}\b')
    
    return patterns


def build_member_patterns(member_name: str, member_type: str) -> Dict[str, Pattern]:
    """Build regex patterns for detecting member usage."""
    patterns = {}
    escaped_name = re.escape(member_name)
    
    if member_type == 'method':
        # Method call
        patterns['call'] = re.compile(rf'\b{escaped_name}\s*\(')
        # Method reference
        patterns['reference'] = re.compile(rf'::\s*{escaped_name}\b')
        # Override
        patterns['override'] = re.compile(rf'\boverride\b[^{{\n]*\b{escaped_name}\s*\(')
    
    elif member_type == 'field':
        # Dot access
        patterns['dot_access'] = re.compile(rf'\.(\s*){escaped_name}\b')
        # This access
        patterns['this_access'] = re.compile(rf'\bthis\.(\s*){escaped_name}\b')
        # Reference
        patterns['reference'] = re.compile(rf'::\s*{escaped_name}\b')
        # Named argument (Kotlin)
        patterns['named_arg'] = re.compile(rf'\b{escaped_name}\s*=')
    
    return patterns


def scan_file_for_usage(path: Path, patterns: Dict[str, Pattern], same_pkg_ok: bool, 
                       target_pkg: str, strict_import: bool) -> Tuple[int, List[Tuple[int, str]], Optional[str]]:
    """
    Scan a single file for usage of the target class.
    Returns (total_matches, line_hits, file_package).
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except (OSError, IOError):
        return 0, [], None
    
    # Extract package from this file
    file_package = ""
    package_match = re.search(r'^\s*package\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s*;?\s*$', content, re.MULTILINE)
    if package_match:
        file_package = package_match.group(1)
    
    # Strip comments and strings
    clean_content = strip_comments_and_strings(content)
    
    # Check for import or direct FQN usage first
    has_import_or_fqn = (
        patterns['import_fqn'].search(clean_content) or
        patterns['import_class'].search(clean_content) or
        patterns['direct_fqn'].search(clean_content)
    )
    
    line_hits = []
    total_matches = 0
    lines = content.splitlines()
    clean_lines = clean_content.splitlines()
    
    for i, (original_line, clean_line) in enumerate(zip(lines, clean_lines)):
        line_num = i + 1
        line_matches = 0
        
        # Check import and FQN patterns
        for pattern_name in ['import_fqn', 'import_class', 'direct_fqn']:
            if patterns[pattern_name].search(clean_line):
                line_matches += len(patterns[pattern_name].findall(clean_line))
        
        # Check simple name patterns
        simple_name_matches = 0
        for pattern_name in ['constructor', 'type_annotation', 'generic', 'annotation', 'instanceof', 'simple_name']:
            matches = patterns[pattern_name].findall(clean_line)
            simple_name_matches += len(matches)
        
        # Apply filtering rules for simple name matches
        if simple_name_matches > 0:
            if strict_import and not has_import_or_fqn:
                simple_name_matches = 0
            elif not same_pkg_ok and file_package != target_pkg and not has_import_or_fqn:
                simple_name_matches = 0
        
        line_matches += simple_name_matches
        
        if line_matches > 0:
            line_hits.append((line_num, original_line.strip()))
            total_matches += line_matches
    
    return total_matches, line_hits, file_package


def scan_file_for_member_usage(path: Path, class_name: str, fqn: str, members: List[str], 
                             member_type: str, same_pkg_ok: bool, target_pkg: str, 
                             strict_import: bool) -> Tuple[int, List[Tuple[int, str, str, str]], Optional[str]]:
    """
    Scan a single file for usage of target class members.
    Returns (total_matches, line_hits_with_member, file_package).
    line_hits_with_member is List[Tuple[line_num, snippet, member_name, kind]]
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except (OSError, IOError):
        return 0, [], None
    
    # Extract package from this file
    file_package = ""
    package_match = re.search(r'^\s*package\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s*;?\s*$', content, re.MULTILINE)
    if package_match:
        file_package = package_match.group(1)
    
    # Strip comments and strings
    clean_content = strip_comments_and_strings(content)
    
    # Check for class import or direct FQN usage (file-level filter)
    class_patterns = build_patterns(fqn, class_name)
    has_import_or_fqn = (
        class_patterns['import_fqn'].search(clean_content) or
        class_patterns['import_class'].search(clean_content) or
        class_patterns['direct_fqn'].search(clean_content)
    )
    
    # If strict import is required and no import/FQN found, skip
    if strict_import and not has_import_or_fqn:
        return 0, [], file_package
    
    # If not same package ok and no import/FQN, check if same package
    if not same_pkg_ok and not has_import_or_fqn and file_package != target_pkg:
        # Still allow if class name appears in some form
        if not class_patterns['simple_name'].search(clean_content):
            return 0, [], file_package
    
    # Collect variable names typed as ClassName for better matching
    typed_vars = set()
    # Kotlin: val/var varName: ClassName
    kotlin_typed = re.findall(rf'(?:val|var)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*{re.escape(class_name)}\b', clean_content)
    typed_vars.update(kotlin_typed)
    # Java: ClassName varName (simplified)
    java_typed = re.findall(rf'{re.escape(class_name)}\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', clean_content)
    typed_vars.update(java_typed)
    
    line_hits = []
    total_matches = 0
    lines = content.splitlines()
    clean_lines = clean_content.splitlines()
    
    for i, (original_line, clean_line) in enumerate(zip(lines, clean_lines)):
        line_num = i + 1
        
        for member_name in members:
            member_patterns = build_member_patterns(member_name, member_type)
            line_matches = 0
            
            for pattern_name, pattern in member_patterns.items():
                matches = pattern.findall(clean_line)
                if matches:
                    # Check if it's a qualified access with known variables
                    if pattern_name in ['dot_access', 'this_access'] and typed_vars:
                        # Look for var.member pattern
                        for var_name in typed_vars:
                            qualified_pattern = rf'\b{re.escape(var_name)}\s*\??\.\s*{re.escape(member_name)}\b'
                            if re.search(qualified_pattern, clean_line):
                                line_matches += len(re.findall(qualified_pattern, clean_line))
                                break
                        else:
                            # Also allow ClassName.member (static/companion)
                            static_pattern = rf'\b{re.escape(class_name)}\s*\.\s*{re.escape(member_name)}\b'
                            if re.search(static_pattern, clean_line):
                                line_matches += len(re.findall(static_pattern, clean_line))
                            # Or direct .member if we have import/FQN
                            elif has_import_or_fqn:
                                line_matches += len(matches)
                    else:
                        line_matches += len(matches)
            
            if line_matches > 0:
                line_hits.append((line_num, original_line.strip(), member_name, member_type))
                total_matches += line_matches
    
    return total_matches, line_hits, file_package


def iter_source_files(root: Path, exts: Set[str], follow_symlinks: bool, 
                     ignore: GitignoreMatcher) -> Iterator[Path]:
    """Iterate over source files in the directory tree."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        current_dir = Path(dirpath)
        
        # Filter out ignored directories
        dirnames[:] = [d for d in dirnames if not ignore.is_ignored(current_dir / d)]
        
        for filename in filenames:
            file_path = current_dir / filename
            
            # Check extension
            if file_path.suffix not in exts:
                continue
            
            # Check if ignored
            if ignore.is_ignored(file_path):
                continue
            
            yield file_path


def print_human(results: List, with_lines: bool, color: bool, mode: str, limit: Optional[int] = None) -> None:
    """Print results in human-readable table format."""
    if not results:
        print("No usage found.")
        return
    
    # Apply limit if specified
    if limit and len(results) > limit:
        results = results[:limit]
        print(f"Showing first {limit} results (of {len(results)} total)")
    
    # ANSI color codes
    if color:
        BOLD = '\033[1m'
        GREEN = '\033[32m'
        BLUE = '\033[34m'
        YELLOW = '\033[33m'
        RESET = '\033[0m'
    else:
        BOLD = GREEN = BLUE = YELLOW = RESET = ''
    
    # Calculate column widths
    max_path_len = max(len(str(result[0])) for result in results)
    max_matches_len = max(len(str(result[1])) for result in results)
    
    # Print header
    member_header = " Member(s)" if mode != 'class' else ""
    print(f"{BOLD}{'Path':<{max_path_len}} {'Matches':<{max_matches_len}}{' Lines' if with_lines else ''}{member_header}{RESET}")
    print("-" * (max_path_len + max_matches_len + (6 if with_lines else 0) + (len(member_header))))
    
    # Print results
    for result in sorted(results):
        if mode == 'class':
            path, matches, line_hits, _ = result
            line_info = ""
            if with_lines and line_hits:
                line_nums = [str(line_num) for line_num, _ in line_hits]
                line_info = f" {BLUE}{','.join(line_nums)}{RESET}"
            
            print(f"{GREEN}{str(path):<{max_path_len}}{RESET} {matches:<{max_matches_len}}{line_info}")
            
            if with_lines:
                for line_num, snippet in line_hits:
                    print(f"  {line_num:4d}: {snippet[:80]}{'...' if len(snippet) > 80 else ''}")
        else:
            path, matches, line_hits_with_member, _ = result
            # Collect unique members for this file
            members_in_file = set()
            if line_hits_with_member:
                members_in_file = {member for _, _, member, _ in line_hits_with_member}
            
            line_info = ""
            if with_lines and line_hits_with_member:
                line_nums = [str(line_num) for line_num, _, _, _ in line_hits_with_member]
                line_info = f" {BLUE}{','.join(line_nums)}{RESET}"
            
            member_info = f" {YELLOW}{','.join(sorted(members_in_file))}{RESET}"
            
            print(f"{GREEN}{str(path):<{max_path_len}}{RESET} {matches:<{max_matches_len}}{line_info}{member_info}")
            
            if with_lines:
                for line_num, snippet, member, kind in line_hits_with_member:
                    print(f"  {line_num:4d}: {YELLOW}{kind} {member}{RESET}  {snippet[:60]}{'...' if len(snippet) > 60 else ''}")


def print_json(results: List, target_meta: Tuple[str, str, str], mode: str, 
              members: List[str], with_lines: bool) -> None:
    """Print results in JSON format."""
    package, class_name, fqn = target_meta
    
    output = {
        "target": {
            "package": package,
            "class_name": class_name,
            "fqn": fqn
        },
        "mode": mode,
        "members": members,
        "results": []
    }
    
    for result in results:
        if mode == 'class':
            path, matches, line_hits, file_package = result
            result_item = {
                "path": str(path).replace('\\', '/'),  # POSIX-style paths
                "count": matches,
                "package": file_package,
                "line_hits": []
            }
            
            if with_lines:
                result_item["line_hits"] = [
                    {"line": line_num, "snippet": snippet}
                    for line_num, snippet in line_hits
                ]
        else:
            path, matches, line_hits_with_member, file_package = result
            result_item = {
                "path": str(path).replace('\\', '/'),  # POSIX-style paths
                "count": matches,
                "package": file_package,
                "line_hits": []
            }
            
            if with_lines:
                result_item["line_hits"] = [
                    {"line": line_num, "member": member, "kind": kind, "snippet": snippet}
                    for line_num, snippet, member, kind in line_hits_with_member
                ]
        
        output["results"].append(result_item)
    
    print(json.dumps(output, indent=2))


def prompt_for_target_path(max_attempts: int = 3) -> Path:
    """Interactively prompt for target file path with validation."""
    for attempt in range(max_attempts):
        try:
            path_input = input("Enter the absolute path to the target Kotlin/Java class file (.kt/.kts/.java): ").strip()
            
            if not path_input:
                print("Error: Empty path provided.")
                continue
            
            # Expand ~ and environment variables
            expanded_path = os.path.expanduser(os.path.expandvars(path_input))
            path = Path(expanded_path).resolve()
            
            # Validate existence and readability
            if not path.exists():
                print(f"Error: File does not exist: {path}")
                continue
            
            if not path.is_file():
                print(f"Error: Path is not a file: {path}")
                continue
            
            # Validate extension
            if path.suffix not in {'.kt', '.kts', '.java'}:
                print(f"Error: Unsupported file extension. Expected .kt, .kts, or .java, got: {path.suffix}")
                continue
            
            # Test readability
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.read(1)  # Try to read one character
            except (OSError, IOError) as e:
                print(f"Error: Cannot read file: {e}")
                continue
            
            return path
            
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            sys.exit(2)
        except Exception as e:
            print(f"Error: {e}")
    
    print(f"Error: Failed to get valid target path after {max_attempts} attempts.")
    sys.exit(2)


def prompt_for_mode_and_members(available_members: Dict[str, List[str]], max_attempts: int = 3) -> Tuple[str, List[str]]:
    """Prompt for search mode and member selection."""
    # Mode selection
    for attempt in range(max_attempts):
        try:
            print("\nSearch mode:")
            print("  [1] Class usages (current behavior)")
            print("  [2] Method usages")
            print("  [3] Field/Property usages")
            mode_input = input("Choose 1/2/3: ").strip()
            
            if mode_input == '1':
                return 'class', []
            elif mode_input == '2':
                mode = 'method'
                member_type = 'methods'
                break
            elif mode_input == '3':
                mode = 'field'
                member_type = 'fields'
                break
            else:
                print("Error: Invalid choice. Please enter 1, 2, or 3.")
                continue
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            sys.exit(2)
    else:
        print(f"Error: Failed to get valid mode after {max_attempts} attempts.")
        sys.exit(2)
    
    # Member selection
    available = available_members[member_type]
    if not available:
        print(f"Error: No {member_type} found in target class.")
        sys.exit(2)
    
    print(f"\nAvailable {member_type}: {', '.join(available)}")
    
    for attempt in range(max_attempts):
        try:
            member_input = input(f"Enter {member_type} (comma-separated names, /regex/, or 'all'): ").strip()
            
            if not member_input:
                print("Error: Empty input provided.")
                continue
            
            if member_input.lower() == 'all':
                return mode, available
            
            # Check if it's a regex
            if member_input.startswith('/') and member_input.endswith('/') and len(member_input) > 2:
                regex_pattern = member_input[1:-1]
                try:
                    regex = re.compile(regex_pattern)
                    matched_members = [member for member in available if regex.search(member)]
                    if not matched_members:
                        print(f"Error: Regex '{regex_pattern}' matched no {member_type}.")
                        continue
                    return mode, matched_members
                except re.error as e:
                    print(f"Error: Invalid regex '{regex_pattern}': {e}")
                    continue
            
            # Parse comma-separated names
            member_names = [name.strip() for name in member_input.split(',') if name.strip()]
            if not member_names:
                print("Error: No valid member names provided.")
                continue
            
            # Validate member names
            invalid_members = [name for name in member_names if name not in available]
            if invalid_members:
                print(f"Error: Unknown {member_type}: {', '.join(invalid_members)}")
                print(f"Available {member_type}: {', '.join(available)}")
                continue
            
            return mode, member_names
            
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            sys.exit(2)
    
    print(f"Error: Failed to get valid {member_type} after {max_attempts} attempts.")
    sys.exit(2)


def open_in_editor(file_path: Path, line_num: int = 1) -> bool:
    """Open file in editor. Returns True if successful."""
    try:
        # Check environment variables for editor preference
        editor = os.environ.get('VISUAL') or os.environ.get('EDITOR', '')
        
        if 'code' in editor.lower() or shutil.which('code'):
            # VS Code
            subprocess.run(['code', '-g', f"{file_path}:{line_num}"], check=True)
            return True
        elif 'idea' in editor.lower() or shutil.which('idea'):
            # IntelliJ IDEA
            subprocess.run(['idea', '--line', str(line_num), str(file_path)], check=True)
            return True
        elif 'studio' in editor.lower() or shutil.which('studio'):
            # Android Studio
            subprocess.run(['studio', '--line', str(line_num), str(file_path)], check=True)
            return True
        else:
            # Platform-specific fallbacks
            if sys.platform == 'darwin':  # macOS
                # Try Android Studio first
                try:
                    subprocess.run(['open', '-a', 'Android Studio', '--args', '--line', str(line_num), str(file_path)], check=True)
                    return True
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Generic open
                    subprocess.run(['open', str(file_path)], check=True)
                    return True
            elif sys.platform.startswith('linux'):
                subprocess.run(['xdg-open', str(file_path)], check=True)
                return True
            elif sys.platform == 'win32':
                subprocess.run(['start', '', str(file_path)], shell=True, check=True)
                return True
        
        return False
        
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Warning: Could not open {file_path}:{line_num} in editor: {e}", file=sys.stderr)
        return False


def handle_open_workflow(results: List, mode: str, select_mode: bool) -> None:
    """Handle opening files in editor workflow."""
    if not results:
        print("No results to open.")
        return
    
    # Collect all hits with line numbers
    hits = []
    for result in results:
        if mode == 'class':
            path, _, line_hits, _ = result
            for line_num, snippet in line_hits:
                hits.append((path, line_num, snippet, '', ''))
        else:
            path, _, line_hits_with_member, _ = result
            for line_num, snippet, member, kind in line_hits_with_member:
                hits.append((path, line_num, snippet, member, kind))
    
    if not hits:
        # Open files without line numbers
        for result in results:
            path = result[0]
            if not open_in_editor(path):
                print(f"Failed to open: {path}")
        return
    
    if select_mode:
        # Interactive selection
        print("\nSelect files to open:")
        for i, (path, line_num, snippet, member, kind) in enumerate(hits, 1):
            member_info = f" {kind} {member}" if member else ""
            print(f"[{i}] {path}:{line_num}{member_info}")
            print(f"    {snippet[:60]}{'...' if len(snippet) > 60 else ''}")
        
        try:
            selection = input("\nEnter numbers (e.g., 1,2,5) or 'all' or 'none': ").strip()
            
            if selection.lower() == 'none':
                return
            elif selection.lower() == 'all':
                selected_hits = hits
            else:
                # Parse numbers
                try:
                    indices = [int(x.strip()) - 1 for x in selection.split(',') if x.strip()]
                    selected_hits = [hits[i] for i in indices if 0 <= i < len(hits)]
                except (ValueError, IndexError):
                    print("Error: Invalid selection.")
                    return
            
            for path, line_num, _, _, _ in selected_hits:
                open_in_editor(path, line_num)
                
        except KeyboardInterrupt:
            print("\nSelection cancelled.")
    else:
        # Open all
        for path, line_num, _, _, _ in hits:
            open_in_editor(path, line_num)


def run_self_test() -> int:
    """Run built-in self-test and return exit code."""
    print("Running self-test...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Create test structure
        # .gitignore
        gitignore_path = temp_path / '.gitignore'
        gitignore_path.write_text('build/\n*.tmp\n')
        
        # Target file with methods and fields
        target_path = temp_path / 'Foo.kt'
        target_path.write_text('''package com.example

data class Foo(val id: Int, var name: String) {
    fun doSomething() {}
    fun helper(x: Int) = x
    val computed: String get() = "test"
}
''')
        
        # Test files
        # 1. File with method usage
        (temp_path / 'MethodUser.kt').write_text('''package com.other
import com.example.Foo

class MethodUser {
    val foo = Foo(1, "test")
    
    fun test() {
        foo.doSomething()
        foo.helper(42)
    }
}
''')
        
        # 2. File with field usage
        (temp_path / 'FieldUser.kt').write_text('''package com.other
import com.example.Foo

class FieldUser {
    val f: Foo = Foo(1, "a")
    
    fun printName() {
        println(f.name)
        println(f.id)
    }
}
''')
        
        # 3. File with override
        (temp_path / 'Override.kt').write_text('''package com.other
import com.example.Foo

class SubClass : SomeBase() {
    override fun doSomething() {
        super.doSomething()
    }
}
''')
        
        # 4. File with false positives
        (temp_path / 'FalsePositives.kt').write_text('''package com.test

class FalsePositives {
    // This mentions doSomething in a comment
    val message = "doSomething is a method"
    val realUsage = com.example.Foo(1, "test")
    
    fun test() {
        realUsage.name = "updated"
    }
}
''')
        
        # 5. File in ignored directory
        build_dir = temp_path / 'build'
        build_dir.mkdir()
        (build_dir / 'Generated.kt').write_text('''package com.generated
import com.example.Foo

class Generated {
    val foo = Foo(1, "test")
    fun test() {
        foo.doSomething()
    }
}
''')
        
        try:
            # Parse target
            package, class_name, fqn = parse_target_metadata(target_path)
            assert package == 'com.example', f"Expected package 'com.example', got '{package}'"
            assert class_name == 'Foo', f"Expected class 'Foo', got '{class_name}'"
            assert fqn == 'com.example.Foo', f"Expected FQN 'com.example.Foo', got '{fqn}'"
            
            # Parse members
            with open(target_path, 'r') as f:
                content = f.read()
            members = parse_target_members(content, class_name)
            
            assert 'doSomething' in members['methods'], f"Expected 'doSomething' in methods, got {members['methods']}"
            assert 'helper' in members['methods'], f"Expected 'helper' in methods, got {members['methods']}"
            assert 'id' in members['fields'], f"Expected 'id' in fields, got {members['fields']}"
            assert 'name' in members['fields'], f"Expected 'name' in fields, got {members['fields']}"
            
            # Create ignore matcher
            ignore = GitignoreMatcher(temp_path)
            
            # Test class mode
            class_patterns = build_patterns(fqn, class_name)
            class_results = []
            for file_path in iter_source_files(temp_path, {'.kt', '.kts', '.java'}, False, ignore):
                if file_path == target_path:
                    continue
                
                matches, line_hits, file_package = scan_file_for_usage(
                    file_path, class_patterns, False, package, False
                )
                
                if matches > 0:
                    class_results.append((file_path, matches, line_hits, file_package))
            
            class_files = {r[0].name for r in class_results}
            expected_class_files = {'MethodUser.kt', 'FieldUser.kt', 'FalsePositives.kt'}
            if not expected_class_files.issubset(class_files):
                missing = expected_class_files - class_files
                print(f"FAIL: Missing expected class usage files: {missing}")
                return 2
            
            # Test method mode
            method_results = []
            for file_path in iter_source_files(temp_path, {'.kt', '.kts', '.java'}, False, ignore):
                if file_path == target_path:
                    continue
                
                matches, line_hits, file_package = scan_file_for_member_usage(
                    file_path, class_name, fqn, ['doSomething'], 'method', False, package, False
                )
                
                if matches > 0:
                    method_results.append((file_path, matches, line_hits, file_package))
            
            method_files = {r[0].name for r in method_results}
            if 'MethodUser.kt' not in method_files:
                print(f"FAIL: Expected MethodUser.kt in method results, got {method_files}")
                return 2
            
            # Test field mode
            field_results = []
            for file_path in iter_source_files(temp_path, {'.kt', '.kts', '.java'}, False, ignore):
                if file_path == target_path:
                    continue
                
                matches, line_hits, file_package = scan_file_for_member_usage(
                    file_path, class_name, fqn, ['name'], 'field', False, package, False
                )
                
                if matches > 0:
                    field_results.append((file_path, matches, line_hits, file_package))
            
            field_files = {r[0].name for r in field_results}
            expected_field_files = {'FieldUser.kt', 'FalsePositives.kt'}
            if not expected_field_files.issubset(field_files):
                missing = expected_field_files - field_files
                print(f"FAIL: Missing expected field usage files: {missing}")
                return 2
            
            # Test that ignored files are not found
            all_found_files = class_files | method_files | field_files
            if 'Generated.kt' in all_found_files:
                print("FAIL: Should not find files in ignored directories")
                return 2
            
            print("PASS: All self-tests completed successfully")
            return 0
            
        except Exception as e:
            print(f"FAIL: Self-test error: {e}")
            return 2


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Find all Kotlin/Java files that use a given class or its members',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s
  %(prog)s --mode method --member "doSomething,helper"
  %(prog)s --mode field --member "/^id.*/" --json --with-lines
  %(prog)s --root /path/to/project --open
  %(prog)s --select --strict-import --same-package-ok
        '''
    )
    
    parser.add_argument('--root', type=str, default='.',
                       help='Search root directory (default: current directory)')
    parser.add_argument('--mode', choices=['class', 'method', 'field'],
                       help='Search mode (default: interactive selection)')
    parser.add_argument('--member', type=str,
                       help='Member names (comma-separated or /regex/) for method/field modes')
    parser.add_argument('--json', action='store_true',
                       help='Output JSON format')
    parser.add_argument('--with-lines', action='store_true',
                       help='Include line numbers and snippets in output')
    parser.add_argument('--strict-import', action='store_true',
                       help='Only report files with explicit imports or FQN usage')
    parser.add_argument('--same-package-ok', action='store_true',
                       help='Allow simple name matches if in same package as target')
    parser.add_argument('--ext', type=str, default='.kt,.kts,.java',
                       help='Comma-separated file extensions to scan (default: .kt,.kts,.java)')
    parser.add_argument('--max-workers', type=int,
                       default=min(32, (os.cpu_count() or 1) + 4),
                       help='Maximum number of worker threads')
    parser.add_argument('--follow-symlinks', action='store_true',
                       help='Follow symbolic links during directory traversal')
    parser.add_argument('--no-color', action='store_true',
                       help='Disable ANSI color output')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging to stderr')
    parser.add_argument('--open', action='store_true',
                       help='Open all matching files in editor')
    parser.add_argument('--select', action='store_true',
                       help='Interactively select which files to open in editor')
    parser.add_argument('--limit', type=int,
                       help='Limit number of results shown in human output')
    parser.add_argument('--self-test', action='store_true',
                       help='Run built-in self-test and exit')
    
    args = parser.parse_args(argv)
    
    # Handle self-test
    if args.self_test:
        return run_self_test()
    
    # Check pathspec dependency
    if not HAS_PATHSPEC:
        print("Warning: pathspec not installed. .gitignore files will be ignored.", file=sys.stderr)
        print("Install with: pip install pathspec", file=sys.stderr)
        if args.verbose:
            print("Continuing without .gitignore support...", file=sys.stderr)
    
    # Validate and normalize root
    try:
        root = Path(args.root).resolve()
        if not root.exists():
            print(f"Error: Root directory does not exist: {root}", file=sys.stderr)
            return 2
        if not root.is_dir():
            print(f"Error: Root path is not a directory: {root}", file=sys.stderr)
            return 2
    except Exception as e:
        print(f"Error: Invalid root path: {e}", file=sys.stderr)
        return 2
    
    # Parse extensions
    exts = {ext.strip() for ext in args.ext.split(',') if ext.strip()}
    if not exts:
        print("Error: No valid extensions provided", file=sys.stderr)
        return 2
    
    # Ensure extensions start with dot
    exts = {ext if ext.startswith('.') else f'.{ext}' for ext in exts}
    
    # Interactive prompt for target file
    target_path = prompt_for_target_path()
    
    if args.verbose:
        print(f"Target file: {target_path}", file=sys.stderr)
        print(f"Search root: {root}", file=sys.stderr)
        print(f"Extensions: {exts}", file=sys.stderr)
    
    # Parse target metadata
    try:
        target_package, class_name, fqn = parse_target_metadata(target_path)
        if args.verbose:
            print(f"Target class: {class_name} (FQN: {fqn})", file=sys.stderr)
    except Exception as e:
        print(f"Error parsing target file: {e}", file=sys.stderr)
        return 2
    
    # Parse target members
    try:
        with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
            target_content = f.read()
        available_members = parse_target_members(target_content, class_name)
        if args.verbose:
            print(f"Found methods: {available_members['methods']}", file=sys.stderr)
            print(f"Found fields: {available_members['fields']}", file=sys.stderr)
    except Exception as e:
        print(f"Error parsing target members: {e}", file=sys.stderr)
        return 2
    
    # Determine search mode and members
    if args.mode:
        mode = args.mode
        if mode == 'class':
            selected_members = []
        else:
            if not args.member:
                print(f"Error: --member is required when --mode is {mode}", file=sys.stderr)
                return 2
            
            member_input = args.member
            member_type = 'methods' if mode == 'method' else 'fields'
            available = available_members[member_type]
            
            if not available:
                print(f"Error: No {member_type} found in target class.", file=sys.stderr)
                return 2
            
            if member_input.lower() == 'all':
                selected_members = available
            elif member_input.startswith('/') and member_input.endswith('/') and len(member_input) > 2:
                # Regex
                regex_pattern = member_input[1:-1]
                try:
                    regex = re.compile(regex_pattern)
                    selected_members = [member for member in available if regex.search(member)]
                    if not selected_members:
                        print(f"Error: Regex '{regex_pattern}' matched no {member_type}.", file=sys.stderr)
                        return 2
                except re.error as e:
                    print(f"Error: Invalid regex '{regex_pattern}': {e}", file=sys.stderr)
                    return 2
            else:
                # Comma-separated names
                member_names = [name.strip() for name in member_input.split(',') if name.strip()]
                invalid_members = [name for name in member_names if name not in available]
                if invalid_members:
                    print(f"Error: Unknown {member_type}: {', '.join(invalid_members)}", file=sys.stderr)
                    print(f"Available {member_type}: {', '.join(available)}", file=sys.stderr)
                    return 2
                selected_members = member_names
    else:
        # Interactive mode selection
        mode, selected_members = prompt_for_mode_and_members(available_members)
    
    if args.verbose:
        print(f"Search mode: {mode}", file=sys.stderr)
        if selected_members:
            print(f"Selected members: {selected_members}", file=sys.stderr)
    
    # Create gitignore matcher
    ignore = GitignoreMatcher(root, args.follow_symlinks)
    
    # Collect all source files
    source_files = list(iter_source_files(root, exts, args.follow_symlinks, ignore))
    
    if args.verbose:
        print(f"Found {len(source_files)} source files to scan", file=sys.stderr)
    
    # Scan files concurrently
    results = []
    
    def scan_file(file_path: Path):
        # Skip the target file itself
        if file_path.resolve() == target_path.resolve():
            return None
        
        if mode == 'class':
            patterns = build_patterns(fqn, class_name)
            matches, line_hits, file_package = scan_file_for_usage(
                file_path, patterns, args.same_package_ok, target_package, args.strict_import
            )
            
            if matches > 0:
                return (file_path, matches, line_hits, file_package)
        else:
            matches, line_hits_with_member, file_package = scan_file_for_member_usage(
                file_path, class_name, fqn, selected_members, mode, 
                args.same_package_ok, target_package, args.strict_import
            )
            
            if matches > 0:
                return (file_path, matches, line_hits_with_member, file_package)
        
        return None
    
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [executor.submit(scan_file, path) for path in source_files]
        
        for future in futures:
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                if args.verbose:
                    print(f"Error scanning file: {e}", file=sys.stderr)
    
    # Handle editor workflow
    if args.open or args.select:
        handle_open_workflow(results, mode, args.select)
    
    # Output results
    if args.json:
        print_json(results, (target_package, class_name, fqn), mode, selected_members, args.with_lines)
    else:
        print_human(results, args.with_lines, not args.no_color, mode, args.limit)
    
    # Return appropriate exit code
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())