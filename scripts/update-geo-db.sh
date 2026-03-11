#!/bin/bash

# ============================================================================
# Download the DB-IP Lite country database for IP geolocation lookups
#
# Source: https://db-ip.com/db/lite.php
# License: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
# Attribution: IP Geolocation by DB-IP (https://db-ip.com)
#
# Usage: ./scripts/update-geo-db.sh [YYYY-MM]
#   If no date is given, defaults to the current year-month.
# ============================================================================

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly GEO_DIR="$ROOT_DIR/server/src/data/geo"

usage() {
    echo "Usage: $(basename "$0") [YYYY-MM]"
    echo "  Downloads the DB-IP Lite country database."
    echo "  Defaults to the current year-month if omitted."
    echo ""
    echo "License: CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/"
    echo "Attribution: IP Geolocation by DB-IP (https://db-ip.com)"
    exit 0
}

main() {
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        usage
    fi

    local date_slug="${1:-$(date +%Y-%m)}"

    # Validate date format
    if [[ ! "$date_slug" =~ ^[0-9]{4}-(0[1-9]|1[0-2])$ ]]; then
        echo "Error: date must be in YYYY-MM format (e.g. 2026-03)" >&2
        exit 1
    fi

    local filename="dbip-country-lite-${date_slug}.csv"
    local url="https://download.db-ip.com/free/${filename}.gz"
    local output_gz="$GEO_DIR/${filename}.gz"
    local output_csv="$GEO_DIR/${filename}"
    local symlink="$GEO_DIR/dbip-country-lite.csv"

    mkdir -p "$GEO_DIR"

    echo "Downloading DB-IP Lite country database (${date_slug})..."
    if ! curl -fSL --retry 3 --retry-delay 5 -o "$output_gz" "$url"; then
        echo "Error: failed to download $url" >&2
        echo "The database is published on the 1st of each month." >&2
        echo "Check https://db-ip.com/db/lite.php for availability." >&2
        exit 1
    fi

    echo "Decompressing..."
    gunzip -f "$output_gz"

    # Validate the CSV has expected structure (ip_start,ip_end,country)
    local line_count
    line_count="$(wc -l < "$output_csv")"
    if [[ "$line_count" -lt 1000 ]]; then
        echo "Error: downloaded file has only $line_count lines — expected 100k+" >&2
        rm -f "$output_csv"
        exit 1
    fi

    # Create/update stable symlink so the loader finds the latest file
    ln -sf "$filename" "$symlink"

    echo "Done. Database saved to $output_csv ($line_count entries)"
    echo ""
    echo "Attribution: IP Geolocation by DB-IP (https://db-ip.com)"
    echo "License: CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/"
}

main "$@"
