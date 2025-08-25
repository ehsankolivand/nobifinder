# nobifinder

A single-file Python tool that finds usage of Kotlin/Java classes and their members across a codebase using intelligent heuristics.

[![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Requirements](#requirements)
- [Usage](#usage)
- [Output Formats](#output-formats)
- [Editor Integration](#editor-integration)
- [.gitignore Handling](#gitignore-handling)
- [Performance Tips](#performance-tips)
- [Troubleshooting](#troubleshooting)
- [Self-test](#self-test)
- [Security & Limitations](#security--limitations)
- [Maintainer & Links](#maintainer--links)
- [License](#license)

## Overview

nobifinder helps you find where a Kotlin/Java **class** or its **methods/fields** are used across your codebase. It works by analyzing source files using regex-based heuristics, respecting `.gitignore` patterns, and providing fast concurrent scanning with optional editor integration.

The tool operates in three modes:
- **Class mode**: Find all usages of a class (imports, constructors, type annotations, etc.)
- **Method mode**: Find specific method calls, overrides, and references
- **Field mode**: Find field/property access, assignments, and references

**Key capabilities**: Comment/string stripping for clean matching, `.gitignore` support via `pathspec`, concurrent file processing, JSON output, and direct editor integration with VS Code, IntelliJ IDEA, and Android Studio.

**Limitations**: Uses heuristic parsing (not full AST), may produce false positives with very common names, and cannot detect reflection/dynamic loading/code generation.

## Features

- **Multi-mode search**: Class usages, method calls, or field/property access
- **Flexible member selection**: Comma-separated names, regex patterns (`/^get.*/`), or `all`
- **Smart filtering**: `--strict-import` (requires explicit imports), `--same-package-ok` (allows same-package usage)
- **Gitignore support**: Respects `.gitignore` files via `pathspec` library
- **Always-ignored directories**: `.git`, `build`, `out`, `dist`, `target`, `.gradle`, `.idea`, `node_modules`
- **Multiple output formats**: Human-readable tables with colors, or structured JSON
- **Line-level details**: `--with-lines` shows exact line numbers and code snippets
- **Editor integration**: `--open`/`--select` opens files directly in VS Code, IDEA, or Android Studio
- **Performance optimizations**: Concurrent scanning, customizable worker threads, file extension filtering
- **Built-in validation**: `--self-test` runs comprehensive test suite

## Installation

To make `nobifinder` globally available (so you can type `nobifinder` in any terminal and it runs in that directory), choose one of these methods:

### macOS/Linux (Recommended)

Create a symlink on your PATH:

```bash
# Make the script executable
chmod +x /absolute/path/to/nobifinder.py

# Create symlink (choose one location)
sudo ln -s /absolute/path/to/nobifinder.py /usr/local/bin/nobifinder
# OR for user-only access:
mkdir -p ~/bin
ln -s /absolute/path/to/nobifinder.py ~/bin/nobifinder

# Ensure the target directory is on PATH
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
exec zsh
```

### macOS/Linux (Shell Function)

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
nobifinder() { python /absolute/path/to/nobifinder.py "$@"; }

# Reload shell
exec $SHELL
```

### Windows

**PowerShell** - Add to your PowerShell profile (`$PROFILE`):

```powershell
function nobifinder { python "C:\absolute\path\to\nobifinder.py" @args }

# Save the profile, then reload:
. $PROFILE
```

**Command Prompt** - Create `nobifinder.cmd` in a directory on PATH (e.g., `%USERPROFILE%\bin\`):

```bat
@echo off
python "C:\absolute\path\to\nobifinder.py" %*
```

Then add `%USERPROFILE%\bin` to your system PATH environment variable.

## Requirements

- **Python 3.6+**
- **Optional**: `pathspec` library for `.gitignore` support
  ```bash
  pip install pathspec
  ```
  
Without `pathspec`, the tool will still work but skip `.gitignore` file processing and only use the always-ignored directory list.

## Usage

### Interactive Mode

Simply run the tool and follow the prompts:

```bash
nobifinder
```

The tool will:
1. Ask for the target class file path
2. Parse the class to find available methods/fields
3. Let you choose search mode (class/method/field)
4. For method/field modes, let you select specific members

### Command Line Examples

```bash
# Find all class usages interactively
nobifinder

# Find specific method usages
nobifinder --mode method --member "doSomething,helper"

# Find fields matching regex with JSON output
nobifinder --mode field --member "/^id.*/" --json --with-lines

# Search in specific directory and open results in editor
nobifinder --root /path/to/project --open

# Interactive file selection for editor
nobifinder --select --strict-import --same-package-ok

# Limit results and disable colors
nobifinder --limit 10 --no-color

# Use custom file extensions and increase worker threads
nobifinder --ext ".kt,.java,.scala" --max-workers 16

# Verbose mode with symlink following
nobifinder --verbose --follow-symlinks
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--root` | `.` | Search root directory |
| `--mode` | *interactive* | Search mode: `class`, `method`, or `field` |
| `--member` | *none* | Member names (comma-separated, `/regex/`, or `all`) for method/field modes |
| `--json` | `false` | Output JSON format instead of human-readable |
| `--with-lines` | `false` | Include line numbers and code snippets in output |
| `--strict-import` | `false` | Only report files with explicit imports or FQN usage |
| `--same-package-ok` | `false` | Allow simple name matches if in same package as target |
| `--ext` | `.kt,.kts,.java` | Comma-separated file extensions to scan |
| `--max-workers` | `min(32, cpu_count + 4)` | Maximum number of worker threads |
| `--follow-symlinks` | `false` | Follow symbolic links during directory traversal |
| `--no-color` | `false` | Disable ANSI color output |
| `--verbose` | `false` | Enable verbose logging to stderr |
| `--open` | `false` | Open all matching files in editor |
| `--select` | `false` | Interactively select which files to open in editor |
| `--limit` | *unlimited* | Limit number of results shown in human output |
| `--self-test` | `false` | Run built-in self-test and exit |

## Output Formats

### Human-readable Format

Default table output with optional colors and line details:

```
Path                                    Matches Lines  Member(s)
----------------------------------------------------------------
src/main/kotlin/UserService.kt          3       12,15  doSomething,helper
src/test/kotlin/UserServiceTest.kt      1       45     doSomething
```

With `--with-lines`:
```
src/main/kotlin/UserService.kt          3       12,15  doSomething,helper
  12: method doSomething  user.doSomething()
  15: method helper       helper(42)
```

### JSON Format

Structured output with `--json`:

**Class mode example:**
```json
{
  "target": {
    "package": "com.example",
    "class_name": "User",
    "fqn": "com.example.User"
  },
  "mode": "class",
  "members": [],
  "results": [
    {
      "path": "src/main/kotlin/UserService.kt",
      "count": 2,
      "package": "com.example.service",
      "line_hits": [
        {"line": 10, "snippet": "import com.example.User"},
        {"line": 25, "snippet": "val user = User(name)"}
      ]
    }
  ]
}
```

**Method/Field mode example:**
```json
{
  "target": {
    "package": "com.example", 
    "class_name": "User",
    "fqn": "com.example.User"
  },
  "mode": "method",
  "members": ["getName", "setEmail"],
  "results": [
    {
      "path": "src/main/kotlin/UserService.kt",
      "count": 2,
      "package": "com.example.service", 
      "line_hits": [
        {"line": 15, "member": "getName", "kind": "method", "snippet": "user.getName()"},
        {"line": 20, "member": "setEmail", "kind": "method", "snippet": "user.setEmail(email)"}
      ]
    }
  ]
}
```

Exit codes: `0` (success with results), `1` (no results found), `2` (error).

## Editor Integration

The `--open` and `--select` flags automatically open matching files in your preferred editor.

### Supported Editors

**Auto-detection priority:**
1. `VISUAL` or `EDITOR` environment variables
2. VS Code (`code` command) - opens with `-g file:line`
3. IntelliJ IDEA (`idea` command) - opens with `--line N file`
4. Android Studio (`studio` command) - opens with `--line N file`
5. Platform fallbacks: `open` (macOS), `xdg-open` (Linux), `start` (Windows)

**Editor commands:**
- **VS Code**: `code -g /path/file.kt:25`
- **IntelliJ IDEA**: `idea --line 25 /path/file.kt`
- **Android Studio**: `studio --line 25 /path/file.kt`

**Usage:**
- `--open`: Opens all matching files automatically
- `--select`: Shows interactive list to choose which files to open

The tool gracefully handles missing editors and continues execution if opening fails.

## .gitignore Handling

nobifinder respects gitignore patterns using the `pathspec` library:

- **Always ignored**: `.git`, `build`, `out`, `dist`, `target`, `.gradle`, `.idea`, `node_modules`
- **Gitignore files**: Loads patterns from all `.gitignore` files found in the directory tree
- **Pattern matching**: Uses `gitwildmatch` syntax (same as Git)
- **Fallback**: Without `pathspec`, only always-ignored directories are skipped

Install `pathspec` for full gitignore support:
```bash
pip install pathspec
```

## Performance Tips

- **Limit search scope**: Use `--root` to search only relevant directories
- **Filter extensions**: Use `--ext` to scan only necessary file types (e.g., `--ext ".kt,.java"`)
- **Adjust concurrency**: Use `--max-workers` to match your system (default is usually optimal)
- **Streaming processing**: Files are read and processed individually to minimize memory usage
- **Early filtering**: Gitignore patterns and extensions filter files before content scanning

## Troubleshooting

### PATH Issues

**macOS/Linux - Command not found:**
```bash
# Check if symlink exists
ls -la /usr/local/bin/nobifinder

# Verify PATH includes the directory
echo $PATH

# Add to PATH if missing
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.zshrc
exec zsh
```

**Windows - Command not recognized:**
```cmd
# Check PATH environment variable
echo %PATH%

# Add directory to PATH via System Properties > Environment Variables
# Or use PowerShell:
$env:PATH += ";C:\path\to\nobifinder\directory"
```

### Editor Integration Issues

**Editor not opening:**
- Set `VISUAL` or `EDITOR` environment variables: `export EDITOR=code`
- Ensure editor commands are on PATH: `which code`, `which idea`, `which studio`
- Check if editor supports command line: `code --help`, `idea --help`
- Use absolute paths if commands aren't found

**Wrong editor opens:**
- Override detection with environment variables
- Check priority: `VISUAL` > `EDITOR` > auto-detection

### Gitignore Not Working

**Files not being ignored:**
```bash
# Install pathspec
pip install pathspec

# Verify .gitignore exists and is readable
cat .gitignore

# Use --verbose to see what files are processed
nobifinder --verbose
```

### No Results Found

**When expecting matches:**
- Try `--same-package-ok` to allow same-package usage without imports
- Remove `--strict-import` to include simple name matches
- Check if target class name is too generic (e.g., "User", "Item")
- Use `--verbose` to see search details
- Verify target file path and class name are correct

### Display Issues

**Garbled colors in terminal:**
```bash
# Disable colors
nobifinder --no-color

# Or set terminal environment
export TERM=xterm-256color
```

## Self-test

Validate the tool installation and functionality:

```bash
nobifinder --self-test
```

The self-test creates a temporary directory structure with test files and validates:
- Target file parsing (package, class, members extraction)
- Class usage detection across multiple files
- Method and field usage scanning
- Gitignore pattern filtering
- Comment/string stripping functionality

Returns exit code `0` on success, `2` on failure.

## Security & Limitations

### Limitations

- **Heuristic parsing**: Uses regex patterns, not full AST analysis
- **False positives**: Very common class names may match unrelated code
- **No reflection detection**: Cannot find dynamic/reflection-based usage
- **No code generation**: Generated code usages may be missed
- **Multi-module projects**: Discovers source sets by directory walking only

### Security Considerations

- Reads all source files in the search directory
- Respects gitignore to avoid scanning sensitive directories
- No external network access or code execution
- Temporary files created only during self-test (cleaned up automatically)

## Maintainer & Links

- **Name**: Ehsan Kolivand
- **Email**: [ehsankolivandeh@gmail.con](mailto:ehsankolivandeh@gmail.con)  
- **LinkedIn**: [https://www.linkedin.com/in/ehsan-koolivand/](https://www.linkedin.com/in/ehsan-koolivand/)

## License

License: *unspecified*
