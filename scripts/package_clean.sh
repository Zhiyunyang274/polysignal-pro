#!/bin/bash
#
# Package Clean Script - Create a clean distribution package
#
# This script creates a clean tarball of the project without:
# - Secrets (.env, .env.*)
# - Virtual environments (.venv/)
# - Data files (data/, logs/, runs/)
# - Cache files (.pytest_cache/, __pycache__/)
# - Database files (*.db, *.sqlite)
# - System files (.DS_Store)
#
# Usage:
#   ./scripts/package_clean.sh [output_dir]
#
# Output:
#   Creates polysignal-pro-clean.tar.gz in the specified directory (or current directory)
#

set -e

# Configuration
PROJECT_NAME="polysignal-pro"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="${1:-$PROJECT_ROOT}"
PACKAGE_NAME="${PROJECT_NAME}-clean.tar.gz"

# Files and directories to exclude
EXCLUDE_PATTERNS=(
    ".env"
    ".env.*"
    ".venv"
    "venv"
    "data"
    "logs"
    "runs"
    ".pytest_cache"
    ".ruff_cache"
    ".mypy_cache"
    ".dmypy_cache"
    "__pycache__"
    "*.pyc"
    "*.pyo"
    ".DS_Store"
    "*.db"
    "*.sqlite"
    "*.sqlite3"
    ".git"
    ".workbuddy"
    "*.egg-info"
    "dist"
    "build"
    ".eggs"
    "*.log"
    ".coverage"
    "htmlcov"
    ".tox"
    ".nox"
    "coverage.xml"
    "*.cover"
    ".cache"
    "*.bak"
    "*.swp"
    "*~"
)

echo "=== Creating Clean Package ==="
echo "Project root: $PROJECT_ROOT"
echo "Output directory: $OUTPUT_DIR"
echo ""

# Build exclude arguments
EXCLUDE_ARGS=""
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
    EXCLUDE_ARGS="$EXCLUDE_ARGS --exclude=$pattern"
done

# Create tarball
echo "Creating tarball with exclusions..."
cd "$PROJECT_ROOT"
tar -czvf "$OUTPUT_DIR/$PACKAGE_NAME" \
    $EXCLUDE_ARGS \
    --exclude="*.tar.gz" \
    --exclude="package_clean.sh" \
    .

echo ""
echo "=== Package Created ==="
echo "Location: $OUTPUT_DIR/$PACKAGE_NAME"
echo ""

# Show package contents (summary)
echo "Package contents summary:"
tar -tzf "$OUTPUT_DIR/$PACKAGE_NAME" | head -50
echo "..."

# Calculate size
PACKAGE_SIZE=$(du -h "$OUTPUT_DIR/$PACKAGE_NAME" | cut -f1)
echo ""
echo "Package size: $PACKAGE_SIZE"
echo ""
echo "=== Safety Verification ==="
echo ""

# Verify no secrets included
echo "Checking for secrets..."
if tar -tzf "$OUTPUT_DIR/$PACKAGE_NAME" | grep -E "^\.env|^\.env\." > /dev/null 2>&1; then
    echo "❌ WARNING: .env files found in package!"
    exit 1
else
    echo "✓ No .env files in package"
fi

# Verify no database files included
echo "Checking for database files..."
if tar -tzf "$OUTPUT_DIR/$PACKAGE_NAME" | grep -E "\.db$|\.sqlite$|\.sqlite3$" > /dev/null 2>&1; then
    echo "❌ WARNING: Database files found in package!"
    exit 1
else
    echo "✓ No database files in package"
fi

# Verify no log files included
echo "Checking for log files..."
if tar -tzf "$OUTPUT_DIR/$PACKAGE_NAME" | grep -E "logs/|\.log$" > /dev/null 2>&1; then
    echo "❌ WARNING: Log files found in package!"
    exit 1
else
    echo "✓ No log files in package"
fi

# Verify no run data included
echo "Checking for run data..."
if tar -tzf "$OUTPUT_DIR/$PACKAGE_NAME" | grep -E "^runs/" > /dev/null 2>&1; then
    echo "❌ WARNING: Run data found in package!"
    exit 1
else
    echo "✓ No run data in package"
fi

echo ""
echo "=== All Safety Checks Passed ==="
echo "Package is safe for distribution."
