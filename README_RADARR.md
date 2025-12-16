# Radarr Integration: Queue + Cron Workflow

This integration uses an asynchronous "Queue & Batch" approach. Unlike a synchronous direct hook, this method queues events for efficient batch processing by a separate cron job. This is secure (no Docker socket in Radarr), efficient (deduplicates rapid imports), and reliable.

## Architecture

1.  **Radarr Hook (`jellyplex-radarr-hook.sh`)**: Runs inside the Radarr container. Triggers on Import/Upgrade/Rename. Atomically appends the movie path to a queue file (e.g., `/media/.jellyplex-queue`).
2.  **Cron Script (`jellyplex-cron.sh`)**: Runs on the Host (Unraid). Checks the queue every few minutes, deduplicates paths, runs the Docker sync container for each movie using `--partial` (which limits the sync to only the specified movie path, rather than the entire library), and notifies Jellyfin.

## Prerequisites

1.  **Shared Storage**: Radarr and the Host must share access to the media folder where the queue file resides.
    *   Example: Radarr maps `/mnt/user/Media` to `/media`. The queue file will be at `/mnt/user/Media/.jellyplex-queue`.
2.  **User Scripts / Cron**: Ability to run scripts on the Host (e.g., Unraid "User Scripts" plugin).

## Installation

### 1. Radarr Hook (Inside Radarr Container)

1.  Copy `jellyplex-radarr-hook.sh` to your Radarr config folder (e.g., `/mnt/user/appdata/radarr/scripts/`).
2.  Make it executable: `chmod +x jellyplex-radarr-hook.sh`.
3.  In Radarr, go to **Settings > Connect > + > Custom Script**.
    *   **Name**: Jellyplex Queue
    *   **Triggers**: Import, Upgrade, Rename.
    *   **Path**: `/config/scripts/jellyplex-radarr-hook.sh` (or wherever it is mapped inside the container).
    *   **Arguments**: (Leave empty).
    *   **Save**.

**Configuration**:
By default, the script writes to `/media/.jellyplex-queue`. If your Radarr uses a different mapping, edit the `QUEUE_DIR` variable in the script or pass it as an environment variable.

### 2. Host Cron Job (On Unraid/Host)

1.  Save `jellyplex-cron.sh` to a persistent location on your host (e.g., `/mnt/user/appdata/scripts/`).
2.  Make it executable: `chmod +x jellyplex-cron.sh`.
3.  Configure the script variables if needed:
    *   `QUEUE_FILE`: Path to the queue file on the host (e.g., `/mnt/user/Media/.jellyplex-queue`).
    *   `MOUNT_SOURCE`: Host path for the media library (e.g., `/mnt/user/Media`).
    *   `JELLYFIN_API_KEY`: Set this environment variable for notifications.
4.  Schedule the script to run every 5 minutes.
    *   **Unraid User Scripts**: Create a new script, paste the content (or call the file), and set schedule to `*/5 * * * *`.

## Environment Variables

| Variable | Script | Description | Default |
| :--- | :--- | :--- | :--- |
| `QUEUE_DIR` | Hook | Directory for queue file (Radarr path) | `/media` |
| `QUEUE_FILE` | Cron | Path to queue file (Host path) | `/mnt/user/Media/.jellyplex-queue` |
| `QUEUE_LOCK_FILE` | Both | Shared lock file for race condition prevention | `/tmp/jellyplex-queue.lock` |
| `MOUNT_SOURCE` | Cron | Host media path to mount in Docker | `/mnt/user/Media` |
| `JELLYFIN_URL` | Cron | Jellyfin URL | `http://localhost:8096` (Use HTTPS in production) |
| `JELLYFIN_API_KEY` | Cron | API Key for notifications | **(Set via Environment Variable)** |

**Note:** The `QUEUE_LOCK_FILE` must be accessible by both the Radarr container and the host. If Radarr runs in a container with limited access to `/tmp`, you may need to configure this to a shared path (e.g., `${QUEUE_DIR}/.jellyplex-queue.lock`).

## Troubleshooting

1.  **Check the Logs**:
    *   Radarr hook logs to `/config/logs/jellyplex-hook.log` (inside container).
    *   Cron script logs to `/mnt/user/appdata/radarr/logs/jellyplex-sync.log`.

2.  **Verify Queue File**:
    *   After an import, check if `.jellyplex-queue` exists in your media folder and contains the movie path.

3.  **Manual Run**:
    *   You can run `./jellyplex-cron.sh` manually on the host to process the queue immediately.
