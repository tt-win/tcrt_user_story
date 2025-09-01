#!/usr/bin/env bash
# backup_and_clean.sh
# 1. Copy specified files from SOURCE_DIR to DEST_DIR
# 2. Delete those files in SOURCE_DIR older than 30 days

set -euo pipefail

SOURCE_DIR="/home/qauser/scripts/test_case_repo_tool"
DEST_DIR="/mnt/qa-test-management"
LOG_FILE="/var/log/backup_and_clean.log"
FILE_PATTERN="*.db"   # change to desired pattern or list of files

mkdir -p "$DEST_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting backup" >> "$LOG_FILE"
# Copy matching files preserving attributes
rsync -av --include="$FILE_PATTERN" --exclude='*' "$SOURCE_DIR/" "$DEST_DIR/" >> "$LOG_FILE" 2>&1 || true

echo "$(date '+%Y-%m-%d %H:%M:%S') - Backup completed" >> "$LOG_FILE"

# Find and delete matching files older than 30 days in source
find "$SOURCE_DIR" -type f -name "$FILE_PATTERN" -mtime +30 -print -delete >> "$LOG_FILE" 2>&1 || true

echo "$(date '+%Y-%m-%d %H:%M:%S') - Cleanup completed" >> "$LOG_FILE"
