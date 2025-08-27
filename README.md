# nobifinder

A powerful single-file Python tool that finds usage of Kotlin/Java classes and their members across codebases using Tree-sitter AST parsing (Kotlin) and intelligent regex heuristics (Java).

[![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)

## Table of Contents

- [Overview](#overview)
- [Features](#features)  
- [Installation](#installation)
- [Dependencies](#dependencies)
- [Engine Modes](#engine-modes)
- [Usage](#usage)
- [Complete Flag Reference](#complete-flag-reference)
- [Output Formats](#output-formats)
- [Editor Integration](#editor-integration)
- [Performance & Optimization](#performance--optimization)
- [Troubleshooting](#troubleshooting)
- [Self-test](#self-test)
- [Security & Limitations](#security--limitations)
- [Maintainer & Links](#maintainer--links)
- [License](#license)

## Overview

nobifinder is a comprehensive code analysis tool that helps you find where Kotlin/Java **classes** and their **methods/fields** are used across your codebase. It offers two parsing engines for maximum accuracy and performance:

- **AST Engine**: Tree-sitter based parsing for precise Kotlin analysis
- **Regex Engine**: Intelligent heuristics for Java and fallback scenarios

The tool operates in three search modes:
- **Class mode**: Find all class usages (imports, constructors, type annotations, etc.)
- **Method mode**: Find method calls, overrides, and references  
- **Field mode**: Find field/property access, assignments, and references

**Key capabilities**: Dual parsing engines, Android Studio integration with clickable links, real-time progress tracking, `.gitignore` support, concurrent processing, JSON output, and direct editor integration.

## Features

### Core Analysis
- **Dual parsing engines**: Tree-sitter AST for Kotlin precision + regex heuristics for Java compatibility
- **Multi-mode search**: Class usages, method calls, or field/property access
- **Flexible member selection**: Comma-separated names, regex patterns (`/^get.*/`), or `all`
- **Smart filtering**: `--strict-import` (requires explicit imports), `--same-package-ok` (allows same-package usage)
- **Comment/string stripping**: Excludes false positives from comments and string literals

### Developer Experience
- **Android Studio integration**: Clickable `at file:line` links with optional clipboard copy (macOS)
- **Interactive CLI**: Guided prompts for target selection and search mode
- **Progress tracking**: Real-time progress bars and scanning statistics
- **Editor integration**: Direct file opening in VS Code, IntelliJ IDEA, and Android Studio
- **Multiple output formats**: Android Studio format (default), colored tables, or structured JSON

### Performance & Compatibility
- **Gitignore support**: Respects `.gitignore` files via `pathspec` library
- **Always-ignored directories**: `.git`, `build`, `out`, `dist`, `target`, `.gradle`, `.idea`, `node_modules`
- **Concurrent scanning**: Customizable worker threads for optimal performance
- **Cross-platform**: Windows, macOS, and Linux support
- **File filtering**: Extension-based filtering and symlink handling

## Installation

### Method 1: Global Command (Recommended)

**macOS/Linux:**
```bash
# Make executable and create symlink
chmod +x nobifinder.py
sudo ln -sf "$(pwd)/nobifinder.py" /usr/local/bin/nobifinder

# Verify installation
nobifinder --help
```

**Windows (PowerShell as Administrator):**
```powershell
# Create wrapper script
$binPath = "$env:USERPROFILE\bin"
New-Item -ItemType Directory -Force -Path $binPath
$scriptPath = "$(Get-Location)\nobifinder.py"
@"
@echo off
python "$scriptPath" %*
"@ | Out-File -FilePath "$binPath\nobifinder.cmd" -Encoding ASCII

# Add to PATH (if not already present)
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($currentPath -notlike "*$binPath*") {
    [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$binPath", "User")
}
```

### Method 2: Shell Function

**Bash/Zsh** - Add to `~/.bashrc` or `~/.zshrc`:
```bash
nobifinder() { python /absolute/path/to/nobifinder.py "$@"; }
```

**PowerShell** - Add to PowerShell profile (`$PROFILE`):
```powershell
function nobifinder { python "C:\absolute\path\to\nobifinder.py" @args }
```

## Dependencies

### Core Requirements
- **Python 3.6+**

### Optional Dependencies (Recommended)
Install for full functionality:

```bash
pip install tree-sitter==0.25.0 tree-sitter-kotlin==1.1.0 tqdm>=4.65.0 pathspec>=0.10.0
```

**Individual components:**
- `tree-sitter` + `tree-sitter-kotlin`: AST parsing engine for Kotlin files
- `tqdm`: Progress bars during scanning  
- `pathspec`: `.gitignore` file processing

**Fallback behavior:**
- **Without Tree-sitter**: Uses regex engine for all files (reduced accuracy for Kotlin)
- **Without tqdm**: No progress bars (functionality unchanged)
- **Without pathspec**: Only hardcoded directories ignored (no `.gitignore` support)

## Engine Modes

nobifinder automatically selects the optimal parsing engine based on file type and availability:

### AST Engine (Default for Kotlin)
**Uses:** Tree-sitter with Kotlin grammar for precise parsing

**Capabilities:**
- Exact class/interface/enum/object declarations
- Function declarations with modifiers (suspend, override, etc.)
- Property declarations (val/var) with type information  
- Constructor calls and object creation
- Annotations with type extraction
- Type references and generic arguments
- Import handling with alias support

**Limitations:**
- Kotlin syntax support up to ~2.1 (limited 2.2+ features)
- Context parameters and newest constructs may not parse correctly

### Regex Engine (Default for Java)
**Uses:** Intelligent regex patterns with heuristic matching

**Capabilities:**
- Class/interface/enum declarations
- Method and field patterns
- Import statement analysis
- Variable type tracking for member usage
- Comment and string literal filtering

**Limitations:**
- Heuristic-based matching may have false positives
- Complex generic syntax may be imprecise
- Nested class handling limitations

### Engine Selection
- **Automatic**: AST for `.kt`/`.kts` files (if available), regex for `.java` and fallback
- **Manual**: Use `--engine ast` or `--engine regex` to force specific engine
- **Fallback**: AST automatically falls back to regex on parsing errors

## Usage

### Quick Start

```bash
# Interactive mode (recommended for first use)
nobifinder

# Find all class usages
nobifinder --mode class

# Find specific methods
nobifinder --mode method --member "doSomething,helper"  

# Find fields matching regex pattern
nobifinder --mode field --member "/^id.*/"
```

### Advanced Examples

```bash
# Force AST engine with progress and stats
nobifinder --engine ast --mode method --member "all" --progress --stats

# JSON output with enhanced line details  
nobifinder --mode field --member "name,email" --json --with-lines

# Search specific directory and open in editor
nobifinder --root /path/to/project --open

# Interactive file selection with strict import checking
nobifinder --select --strict-import --same-package-ok

# High-performance scanning with custom settings
nobifinder --max-workers 16 --ext ".kt,.kts" --no-android-format

# Copy Android Studio links to clipboard (macOS)
nobifinder --copy-links --android-format
```

### Interactive Workflow

1. **Target Selection**: Enter absolute path to Kotlin/Java class file
2. **Mode Selection**: Choose from:
   - `[1]` Class usages (current behavior)  
   - `[2]` Method usages
   - `[3]` Field/Property usages
3. **Member Selection** (for modes 2/3):
   - Comma-separated: `doSomething,helper,onClick`
   - Regex pattern: `/^on[A-Z].*/`  
   - All members: `all`
4. **Results**: View in Android Studio format or table, optionally open in editor

## Complete Flag Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | `.` | Search root directory |
| `--mode` | *interactive* | Search mode: `class`, `method`, or `field` |
| `--member` | *none* | Member names for method/field modes (required with --mode) |
| `--engine` | *auto-detect* | Parsing engine: `ast` or `regex` |
| `--json` | `false` | Output JSON format instead of human-readable |
| `--with-lines` | `true` | Include line numbers and code snippets |
| `--no-lines` | `false` | Disable line numbers and snippets |
| `--strict-import` | `false` | Only report files with explicit imports or FQN usage |
| `--same-package-ok` | `false` | Allow simple name matches in same package |
| `--ext` | `.kt,.kts,.java` | Comma-separated file extensions to scan |
| `--max-workers` | `min(32, cpu+4)` | Maximum worker threads |
| `--follow-symlinks` | `false` | Follow symbolic links during traversal |
| `--no-color` | `false` | Disable ANSI color output |
| `--verbose` | `false` | Enable verbose logging to stderr |
| `--open` | `false` | Open all matching files in editor |
| `--select` | `true` | Interactive file selection for editor (default) |
| `--no-select` | `false` | Disable interactive selection |
| `--limit` | *unlimited* | Limit results shown in human output |
| `--progress` | `false` | Show progress bar during scanning |
| `--stats` | `false` | Show scanning statistics at end |
| `--android-format` | `true` | Output Android Studio clickable format (default) |
| `--no-android-format` | `false` | Use table format instead |
| `--copy-links` | `false` | Copy clickable links to clipboard (macOS only) |
| `--self-test` | `false` | Run built-in test suite and exit |

### Flag Combinations

```bash
# Non-interactive with all options
nobifinder --mode method --member "all" --engine ast --json --no-select

# Performance optimized
nobifinder --max-workers 32 --ext ".kt" --no-android-format --progress

# Minimal output
nobifinder --no-lines --no-color --limit 5 --no-select
```

## Output Formats

### Android Studio Format (Default)

Clickable links that work directly in Android Studio console:

```
📱 Android Studio Clickable Links:
==================================================
at /path/to/src/UserService.kt:12
   → method doSomething  user.doSomething()

at /path/to/src/UserService.kt:15  
   → field name: user.name = "updated"

at /path/to/test/UserServiceTest.kt:45
   → method doSomething  override fun doSomething()
```

**With clipboard copy (macOS):**
```bash
nobifinder --copy-links
# Output: 📋 3 links copied to clipboard!
```

### Table Format

Classic table output with `--no-android-format`:

```
Path                                  Matches Lines    Member(s)
--------------------------------------------------------------------
src/main/kotlin/UserService.kt         3      12,15,20 doSomething,name
src/test/kotlin/UserServiceTest.kt     1      45       doSomething
```

**With line details (`--with-lines`):**
```
src/main/kotlin/UserService.kt         3      12,15,20 doSomething,name
  12: method doSomething  user.doSomething()
  15: field name         user.name = "updated"  
  20: method doSomething  override fun doSomething()
```

### JSON Format

Structured output with v2 schema supporting AST engine:

```json
{
  "target": {
    "package": "com.example",
    "class_name": "User", 
    "fqn": "com.example.User"
  },
  "engine": "ast",
  "mode": "method",
  "members": ["doSomething", "getName"],
  "results": [
    {
      "path": "src/main/kotlin/UserService.kt",
      "count": 2,
      "package": "com.example.service",
      "line_hits": [
        {
          "line": 12,
          "col": 8,
          "member": "doSomething", 
          "kind": "method",
          "snippet": "user.doSomething()"
        },
        {
          "line": 25,
          "col": 12,
          "member": "getName",
          "kind": "method", 
          "snippet": "user.getName()"
        }
      ]
    }
  ]
}
```

**Exit codes:** `0` (results found), `1` (no results), `2` (error)

## Editor Integration

### Supported Editors

**Auto-detection priority:**
1. `$VISUAL` or `$EDITOR` environment variables
2. VS Code (`code` command available)
3. IntelliJ IDEA (`idea` command available)  
4. Android Studio (`studio` command available)
5. Platform fallbacks: `open` (macOS), `xdg-open` (Linux), `start` (Windows)

### Commands Used

- **VS Code**: `code -g /path/file.kt:25`
- **IntelliJ IDEA**: `idea --line 25 /path/file.kt`  
- **Android Studio**: `studio --line 25 /path/file.kt`
- **macOS fallback**: `open -a "Android Studio" --args --line 25 /path/file.kt`

### Usage Modes

**`--open` (Open all files):**
```bash
nobifinder --mode method --member "doSomething" --open
# Opens all matching files automatically in editor
```

**`--select` (Interactive selection - default):**
```bash
nobifinder --mode method --member "doSomething" 
# Shows interactive list:
# [1] /path/UserService.kt:12  method doSomething
# [2] /path/UserTest.kt:45     method doSomething  
# Enter numbers (e.g., 1,2,5) or 'all' or 'none':
```

**Environment Setup:**
```bash
# Override auto-detection
export EDITOR=code
export VISUAL=idea

# Ensure commands are available
which code idea studio
```

## Performance & Optimization

### Engine Performance

**AST Engine (Kotlin):**
- ✅ Higher accuracy, fewer false positives
- ✅ Precise member usage detection  
- ⚠️ Slightly slower than regex
- ⚠️ Limited to supported Kotlin syntax

**Regex Engine (Java/Fallback):**
- ✅ Fast processing speed
- ✅ Broader language compatibility
- ⚠️ Potential false positives
- ⚠️ Less precise member tracking

### Optimization Tips

**Scope Reduction:**
```bash
# Search only specific directory
nobifinder --root src/main/kotlin

# Target specific file types  
nobifinder --ext ".kt,.kts"

# Limit results for large codebases
nobifinder --limit 50
```

**Performance Tuning:**
```bash
# Increase workers for CPU-bound tasks
nobifinder --max-workers 16

# Monitor with progress and stats
nobifinder --progress --stats --verbose

# Disable heavy features for speed
nobifinder --no-android-format --no-lines
```

**Memory Efficiency:**
- Files processed individually (streaming)
- Only matching files kept in memory
- Early filtering via extensions and gitignore

### Benchmark Expectations

Typical performance on modern hardware:
- **Small project** (< 1K files): 1-3 seconds
- **Medium project** (1K-10K files): 5-15 seconds  
- **Large project** (10K+ files): 30-60 seconds

AST engine adds ~10-20% overhead vs regex for Kotlin files.

## Troubleshooting

### Installation Issues

**Command not found (macOS/Linux):**
```bash
# Check symlink
ls -la /usr/local/bin/nobifinder

# Verify PATH
echo $PATH | grep -o '/usr/local/bin'

# Fix PATH
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.zshrc
exec zsh
```

**Command not recognized (Windows):**
```cmd
# Check PATH
echo %PATH%

# Verify script location
dir "%USERPROFILE%\bin\nobifinder.cmd"
```

### Engine Issues

**AST engine not available:**
```bash
# Install Tree-sitter dependencies
pip install tree-sitter==0.25.0 tree-sitter-kotlin==1.1.0

# Test installation
python -c "import tree_sitter; import tree_sitter_kotlin; print('OK')"

# Force engine selection
nobifinder --engine regex  # Use regex if AST fails
```

**Parse errors with AST:**
```bash
# Use verbose mode to see errors
nobifinder --engine ast --verbose

# Check Kotlin version compatibility
# AST supports Kotlin up to ~2.1

# Force regex fallback for problematic files
nobifinder --engine regex
```

### Search Issues

**No results found:**
```bash
# Try relaxed filtering
nobifinder --same-package-ok  # Allow same-package usage

# Remove strict requirements  
nobifinder --no-strict-import  # Include simple name matches

# Check target class
nobifinder --verbose  # See parsing details

# Verify file extensions
nobifinder --ext ".kt,.kts,.java" --verbose
```

**Too many false positives:**
```bash
# Use strict filtering
nobifinder --strict-import  # Require explicit imports

# Try AST engine for better precision
nobifinder --engine ast

# Exclude same-package matches
# (don't use --same-package-ok)
```

### Editor Integration Issues

**Editor not opening:**
```bash
# Check editor availability
which code idea studio

# Set explicit editor
export EDITOR=code
nobifinder --open

# Test editor command manually
code -g /path/to/file.kt:1
```

**Wrong editor opens:**
```bash
# Override auto-detection
export VISUAL=idea  # Takes priority over EDITOR
export EDITOR=code

# Check detection order
nobifinder --verbose --open
```

### Performance Issues

**Slow scanning:**
```bash
# Monitor bottlenecks
nobifinder --progress --stats --verbose

# Reduce scope
nobifinder --root src/main --ext ".kt"

# Increase workers
nobifinder --max-workers 32

# Check gitignore efficiency
nobifinder --verbose  # See ignored files
```

**Memory usage:**
```bash
# Disable line storage for large results
nobifinder --no-lines

# Limit output
nobifinder --limit 100

# Use JSON for programmatic processing
nobifinder --json > results.json
```

### Display Issues

**Garbled output:**
```bash
# Disable colors
nobifinder --no-color

# Use table format
nobifinder --no-android-format

# Check terminal support
echo $TERM
export TERM=xterm-256color
```

**Android Studio links not clickable:**
- Ensure you're running in Android Studio terminal/console
- Links work in "Run" and "Build" console tabs
- Copy to clipboard with `--copy-links` as alternative

## Self-test

Validate installation and functionality:

```bash
nobifinder --self-test
```

The comprehensive test suite validates:

### Test Coverage
- **Target parsing**: Package extraction, class/method/field detection
- **Engine testing**: Both AST and regex engines (if available)
- **Search modes**: Class, method, and field usage detection
- **Filtering**: Gitignore patterns, import requirements, package matching
- **Edge cases**: False positive handling, comment/string exclusion
- **File handling**: Extension filtering, symlink processing

### Test Structure
Creates temporary test project with:
- **Target class**: Kotlin data class with methods, fields, annotations
- **Usage files**: Method calls, property access, type references, annotations
- **False positives**: Comments, strings, unrelated classes  
- **Ignored files**: Files in `build/` directory (gitignore test)

### Expected Output
```
Running self-test...
Testing regex engine...
PASS: regex engine class mode tests completed
Testing ast engine...
PASS: ast engine class mode tests completed
PASS: All self-tests completed successfully
```

**Exit codes**: `0` (success), `2` (failure)

**Troubleshooting test failures:**
```bash
# Run with verbose output
nobifinder --self-test --verbose

# Test individual engines
nobifinder --engine regex --self-test
nobifinder --engine ast --self-test
```

## Security & Limitations

### Security Considerations

**File Access:**
- Reads all source files in search directory
- Respects `.gitignore` to avoid sensitive directories  
- No external network access or code execution
- Temporary files only during self-test (auto-cleanup)

**Privacy:**
- No data collection or telemetry
- All processing performed locally
- Editor integration uses standard command-line interfaces

### Current Limitations

**Parsing Accuracy:**
- **AST engine**: Limited to supported Kotlin syntax (~2.1)
- **Regex engine**: Heuristic matching may have false positives
- **Both**: Cannot detect reflection, dynamic loading, or generated code

**Project Structure:**
- Multi-module projects discovered by directory walking only
- No build system integration (Gradle, Maven, etc.)
- Source sets must be in standard locations

**Language Support:**
- Primary: Kotlin (.kt, .kts) and Java (.java)
- AST engine: Kotlin only
- Regex engine: Basic Java support, extensible patterns

**Member Usage Detection:**
- Best-effort receiver type analysis  
- May miss complex method chaining scenarios
- Static/companion access detection limited

### Known Edge Cases

**Kotlin-specific:**
- Context parameters (Kotlin 2.2+) may not parse correctly
- Some DSL patterns may confuse member detection
- Inline functions and reified generics have limited support

**Java-specific:**
- Complex generic syntax may be imprecise
- Anonymous classes and lambdas have limited member tracking
- Annotation processing results not detected

**General:**
- Very common class names (e.g., "User", "Item") may have noise
- Dynamic proxy usage and reflection calls missed
- Code generation from build plugins not detected

## Maintainer & Links

- **Name**: Ehsan Kolivand
- **Email**: [ehsankolivandeh@gmail.com](mailto:ehsankolivandeh@gmail.com)  
- **LinkedIn**: [https://www.linkedin.com/in/ehsan-koolivand/](https://www.linkedin.com/in/ehsan-koolivand/)


