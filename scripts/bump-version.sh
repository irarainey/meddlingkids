#!/bin/bash

# ============================================================================
# Bump the project version in package.json, pyproject.toml, and their lock files
# Usage: ./scripts/bump-version.sh <version>
# ============================================================================

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly PACKAGE_JSON="$ROOT_DIR/package.json"
readonly PYPROJECT_TOML="$ROOT_DIR/server/pyproject.toml"

usage() {
    echo "Usage: $(basename "$0") <version>"
    echo "  e.g. $(basename "$0") 1.7.2"
    exit 1
}

validate_version() {
    local version="$1"
    if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "Error: version must be in semver format (e.g. 1.7.2)" >&2
        exit 1
    fi
}

main() {
    if [[ $# -ne 1 ]]; then
        usage
    fi

    local version="$1"
    validate_version "$version"

    # Read current versions
    local current_npm
    current_npm="$(node -p "require('$PACKAGE_JSON').version")"
    local current_py
    current_py="$(grep -Po '(?<=^version = ")[^"]+' "$PYPROJECT_TOML")"

    echo "Bumping version: $current_npm / $current_py -> $version"

    # Update package.json (npm handles package-lock.json)
    echo "Updating package.json..."
    cd "$ROOT_DIR"
    npm version "$version" --no-git-tag-version --allow-same-version

    # Update pyproject.toml
    echo "Updating pyproject.toml..."
    sed -i "s/^version = \".*\"/version = \"$version\"/" "$PYPROJECT_TOML"

    # Update uv.lock
    echo "Updating uv.lock..."
    cd "$ROOT_DIR/server"
    uv lock

    echo "Version bumped to $version"
}

main "$@"
