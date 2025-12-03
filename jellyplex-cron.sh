#!/bin/bash
#
# jellyplex-cron.sh
#
# Host-side cron script to process the synchronization queue.
# Reads the queue file created by the Radarr hook, performs partial syncs
# using Docker, and notifies Jellyfin.
#
# Schedule recommendation: */5 * * * * (Every 5 minutes)
#

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Path to the queue file (Must match the location written by Radarr hook, but from Host perspective)
# (Radarr sees this as /Cumflix/.jellyplex-queue due to container path mapping)
QUEUE_FILE="${QUEUE_FILE:-/mnt/user/Media/.jellyplex-queue}"
LOCK_FILE="/tmp/jellyplex-cron.lock"
LOG_FILE="${LOG_FILE:-/mnt/user/appdata/radarr/logs/jellyplex-sync.log}"

# Docker Configuration
SYNC_IMAGE="ghcr.io/plex-migration-homelab/jellyplex-sync:latest"
# Host path to mount into the container as /mnt
MOUNT_SOURCE="${MOUNT_SOURCE:-/mnt/user/Media}"

# Jellyfin Configuration
# SECURITY NOTE: Use HTTPS in production
JELLYFIN_URL="${JELLYFIN_URL:-http://localhost:8096}"
JELLYFIN_API_KEY="${JELLYFIN_API_KEY:-}"

# Library Configuration (Configurable patterns)
# 4K Library
LIB_4K_PATTERN="${LIB_4K_PATTERN:-/movies-4k/}"
SOURCE_4K="${SOURCE_4K:-movies-4k}"
TARGET_4K="${TARGET_4K:-jellyfin/movies-4k}"

# Standard Library
SOURCE_STD="${SOURCE_STD:-movies}"
TARGET_STD="${TARGET_STD:-jellyfin/movies}"

# Warn if Jellyfin API key is not set
if [[ -z "$JELLYFIN_API_KEY" ]]; then
    echo "[$(date)] WARNING: JELLYFIN_API_KEY is not set. Jellyfin notifications will not be sent." >> "$LOG_FILE"
fi

# ==============================================================================
# LOGIC
# ==============================================================================

# Exit if no queue file exists
[[ -f "$QUEUE_FILE" ]] || exit 0

# Prevent concurrent runs
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "[$(date)] Sync already in progress, skipping." >> "$LOG_FILE"
    exit 0
fi

echo "[$(date)] === Starting Batch Sync ===" >> "$LOG_FILE"

# Atomically move queue to processing file
PROCESSING_FILE="${QUEUE_FILE}.processing"
(
    flock -x 201
    mv "$QUEUE_FILE" "$PROCESSING_FILE" 2>/dev/null
) 201>"${LOCK_FILE}.queue"

if [[ ! -f "$PROCESSING_FILE" ]]; then
    echo "[$(date)] No queue file to process." >> "$LOG_FILE"
    exit 0
fi

# Deduplicate paths
PATHS=$(sort -u "$PROCESSING_FILE")

# Check if we have paths
if [[ -z "$PATHS" ]]; then
    rm -f "$PROCESSING_FILE"
    exit 0
fi

FAILED_COUNT=0
SYNCED_PATHS=()

# Process each unique movie
while IFS= read -r movie_path; do
    [[ -z "$movie_path" ]] && continue

    echo "[$(date)] Processing: $movie_path" >> "$LOG_FILE"

    # Smart Path Logic: Detect library type
    # Note: movie_path comes from Radarr, which might use a different path mapping than Host.
    # We pass the raw path to Docker via --partial, and the Python script's resolve_movie_folder
    # logic handles matching it against the container's filesystem.

    # We still need to determine SOURCE/TARGET for the main sync arguments.
    # We guess based on the string.
    if [[ "$movie_path" == *"${LIB_4K_PATTERN}"* ]]; then
        SOURCE_LIB="$SOURCE_4K"
        TARGET_LIB="$TARGET_4K"
    else
        SOURCE_LIB="$SOURCE_STD"
        TARGET_LIB="$TARGET_STD"
    fi

    # Execute Docker Sync
    # We pass --partial "$movie_path" so the container only syncs that specific folder.
    docker run --rm \
        --user 99:100 \
        -v "${MOUNT_SOURCE}:/mnt" \
        "$SYNC_IMAGE" \
        --verbose \
        --delete \
        --create \
        --update-filenames \
        --partial "$movie_path" \
        "/mnt/${SOURCE_LIB}" \
        "/mnt/${TARGET_LIB}" >> "$LOG_FILE" 2>&1

    EXIT_CODE=$?
    if [[ $EXIT_CODE -ne 0 ]]; then
        echo "[$(date)] ERROR: Sync failed for $movie_path (Exit: $EXIT_CODE)" >> "$LOG_FILE"
        ((FAILED_COUNT++))
    else
        SYNCED_PATHS+=("$movie_path")
    fi

done <<< "$PATHS"

# Cleanup
rm -f "$PROCESSING_FILE"

# Fix permissions on target directories (Safety net)
echo "[$(date)] Setting permissions..." >> "$LOG_FILE"
# We define standard targets based on our assumption of layout
TARGET_DIRS=(
    "${MOUNT_SOURCE}/${TARGET_STD}"
    "${MOUNT_SOURCE}/${TARGET_4K}"
)

for target_dir in "${TARGET_DIRS[@]}"; do
    if [[ -d "$target_dir" ]]; then
        chown -R 99:100 "$target_dir" 2>/dev/null
    fi
done

# Jellyfin Notification
# We notify per synced item to be precise, or we could do a full library refresh.
# The user suggested a single batch notification.
# Since we have mixed libraries (movies/movies-4k), a full scan might be overkill but safe.
# However, `Library/Media/Updated` is better for specific paths.
# Let's batch notify the specific paths if API key is present.

if [[ -n "$JELLYFIN_API_KEY" && ${#SYNCED_PATHS[@]} -gt 0 ]]; then
    echo "[$(date)] Notifying Jellyfin..." >> "$LOG_FILE"

    # Calculate Jellyfin paths for all synced items
    # Assumes standard mapping: /Cumflix/movies -> /media/jellyfin/movies
    # Note: We need to know the mapping logic.
    # If movie_path is "/Cumflix/movies/Avatar", we want "/media/jellyfin/movies/Avatar".

    # We construct a JSON array for the Updates
    JSON_UPDATES=""
    for raw_path in "${SYNCED_PATHS[@]}"; do
        # Apply strict sed substitution as requested previously, but using variables
        # Note: We assume Radarr path (/Cumflix) needs to map to Jellyfin internal path (/media)
        # and we use the library names detected earlier.

        # Construct dynamic sed pattern
        # Replace /Cumflix/<source_lib>/ with /media/<target_lib>/
        # We assume standard Radarr mount /Cumflix maps to Host Media (or whatever path prefix is used)

        # We use a rough heuristic: replace the source lib name with target lib name
        # and change the prefix /Cumflix to /media if present.

        JELLYFIN_PATH=$(echo "$raw_path" | sed "s|${SOURCE_4K}|${TARGET_4K}|; s|${SOURCE_STD}|${TARGET_STD}|; s|^/Cumflix/|/media/|")

        # Escape for JSON
        JELLYFIN_PATH_ESCAPED=$(echo "$JELLYFIN_PATH" | sed 's/\\/\\\\/g; s/"/\\"/g')

        if [[ -n "$JSON_UPDATES" ]]; then
            JSON_UPDATES="${JSON_UPDATES},"
        fi
        JSON_UPDATES="${JSON_UPDATES}{\"Path\":\"${JELLYFIN_PATH_ESCAPED}\",\"UpdateType\":\"Created\"}"
    done

    # Send request
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "${JELLYFIN_URL}/Library/Media/Updated" \
        -H "X-Emby-Token: ${JELLYFIN_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"Updates\":[${JSON_UPDATES}]}")

    echo "[$(date)] Jellyfin notification sent (HTTP $HTTP_CODE)" >> "$LOG_FILE"
else
    echo "[$(date)] Skipping Jellyfin notification (No API Key or no successful syncs)" >> "$LOG_FILE"
fi

echo "[$(date)] Batch sync complete: ${#SYNCED_PATHS[@]} synced, $FAILED_COUNT failed." >> "$LOG_FILE"
exit $((FAILED_COUNT > 0 ? 1 : 0))
