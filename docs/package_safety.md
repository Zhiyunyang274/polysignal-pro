# Package Safety Guide

This document describes how to create and verify clean distribution packages of PolySignal Pro that do not contain sensitive data, secrets, or runtime artifacts.

## Files to Exclude

When creating a distribution package, the following files and directories must **NOT** be included:

### Secrets and Configuration
- `.env` - Environment variables (may contain API keys)
- `.env.*` - Environment-specific configuration
- Any files containing API keys, tokens, or credentials

### Virtual Environments
- `.venv/` - Python virtual environment
- `venv/` - Alternative virtual environment directory

### Runtime Data
- `data/` - Database files and cached data
- `logs/` - Application logs
- `runs/` - Paper trading run results

### Cache Files
- `.pytest_cache/` - Pytest cache
- `.ruff_cache/` - Ruff cache
- `.mypy_cache/` - mypy cache
- `.dmypy_cache/` - dmypy cache
- `__pycache__/` - Python bytecode cache
- `*.pyc` - Compiled Python files
- `*.pyo` - Optimized Python bytecode
- `.cache/` - General cache directory

### Database Files
- `*.db` - SQLite database files
- `*.sqlite` - SQLite database files
- `*.sqlite3` - SQLite database files

### System Files
- `.DS_Store` - macOS metadata
- `.workbuddy/` - Local assistant workspace memory
- `*.bak` - Backup files
- `*.swp` - Vim swap files
- `*~` - Editor backup files

### Build Artifacts
- `dist/` - Distribution packages
- `build/` - Build artifacts
- `.eggs/` - Egg files
- `*.egg-info/` - Package metadata
- `.coverage` - Coverage data
- `htmlcov/` - Coverage reports

### Version Control
- `.git/` - Git repository (optional, for source distributions)

## Creating a Clean Package

### Using the Script

Run the provided script:

```bash
./scripts/package_clean.sh
```

This creates `polysignal-pro-clean.tar.gz` in the project root.

### Manual Creation

```bash
tar -czvf polysignal-pro-clean.tar.gz \
    --exclude=.env \
    --exclude=.env.* \
    --exclude=.venv \
    --exclude=venv \
    --exclude=data \
    --exclude=logs \
    --exclude=runs \
    --exclude=.pytest_cache \
    --exclude=.ruff_cache \
    --exclude=.mypy_cache \
    --exclude=.dmypy_cache \
    --exclude=__pycache__ \
    --exclude="*.pyc" \
    --exclude=.DS_Store \
    --exclude="*.db" \
    --exclude="*.sqlite" \
    --exclude=.git \
    --exclude=.workbuddy \
    --exclude="*.egg-info" \
    --exclude=dist \
    --exclude=build \
    .
```

## Verification Checklist

Before distributing a package, verify:

1. **No secrets included**
   ```bash
   tar -tzf package.tar.gz | grep -E "^\.env|^\.env\."
   # Should return nothing
   ```

2. **No database files**
   ```bash
   tar -tzf package.tar.gz | grep -E "\.db$|\.sqlite$"
   # Should return nothing
   ```

3. **No log files**
   ```bash
   tar -tzf package.tar.gz | grep -E "logs/|\.log$"
   # Should return nothing
   ```

4. **No run data**
   ```bash
   tar -tzf package.tar.gz | grep -E "^runs/"
   # Should return nothing
   ```

5. **No virtual environment**
   ```bash
   tar -tzf package.tar.gz | grep -E "^\.venv|^venv/"
   # Should return nothing
   ```

## .gitignore Configuration

Ensure `.gitignore` includes all excluded patterns:

```gitignore
# Secrets
.env
.env.*

# Virtual environments
.venv/
venv/

# Runtime data
data/
logs/
runs/

# Cache
.pytest_cache/
.ruff_cache/
.mypy_cache/
.dmypy_cache/
__pycache__/
*.pyc
.cache/

# Local assistant workspace
.workbuddy/

# Databases
*.db
*.sqlite
*.sqlite3

# System
.DS_Store
*.bak
*.swp
*~

# Build
dist/
build/
*.egg-info/
.eggs/

# Coverage
.coverage
htmlcov/
coverage.xml
```

## Security Notes

1. **Never commit secrets**: Use `.env.example` as a template, never actual `.env` files
2. **Review before packaging**: Always run `tar -tzf package.tar.gz` to review contents
3. **Use environment variables**: In production, inject secrets via environment, not files
4. **Audit regularly**: Periodically review what files are in version control
