# Radarr Direct Hook Integration

This guide explains how to set up the synchronous `jellyplex-direct-hook.sh` script in Radarr. This script replaces the old cron-based trigger system, allowing for immediate synchronization of movies to Jellyfin upon Import, Upgrade, or Rename.

## Prerequisites

1.  **Docker Socket Access**: The Radarr container must have access to the host's Docker socket to execute the sync container.
    *   Mount `/var/run/docker.sock:/var/run/docker.sock` in your Radarr container configuration.
    *   Ensure the `docker` CLI is installed inside the Radarr container (or available via volume mount).

2.  **Path Mappings**:
    *   The script assumes Radarr uses paths starting with `/Cumflix` (mapping to `/mnt/user/Media` on the host).
    *   It assumes `movies` and `movies-4k` libraries exist.

## Installation

1.  **Save the Script**:
    Copy `jellyplex-direct-hook.sh` to a persistent location accessible by your Radarr container (e.g., your Radarr config folder).

    ```bash
    cp jellyplex-direct-hook.sh /mnt/user/appdata/radarr/scripts/
    ```

2.  **Make Executable**:
    Ensure the script has execution permissions:

    ```bash
    chmod +x /mnt/user/appdata/radarr/scripts/jellyplex-direct-hook.sh
    ```

## Radarr Configuration

1.  Open Radarr and navigate to **Settings** > **Connect**.
2.  Click the **+** button and select **Custom Script**.
3.  Configure the settings as follows:
    *   **Name**: Jellyplex Sync (Direct)
    *   **On Grab**: (Unchecked)
    *   **On Import**: (Checked) - *Required for new downloads*
    *   **On Upgrade**: (Checked) - *Required for quality upgrades*
    *   **On Rename**: (Checked) - *Required if you rename files*
    *   **On Movie Delete**: (Unchecked)
    *   **Tags**: (Leave empty or filter as needed)
    *   **Path**: `/config/scripts/jellyplex-direct-hook.sh` (Adjust path to where it is mounted inside the container)

4.  **Click "Test"**.
    *   You should see a green checkmark.
    *   Check the log file (`/mnt/user/appdata/radarr/logs/jellyplex-sync.log`) to confirm the "Test event received" message.

## Environment Variables

The script includes default values, but you can override them by passing environment variables or editing the "Configuration" section at the top of the script.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `JELLYFIN_URL` | Your Jellyfin Server URL | `http://192.168.3.51:8096` |
| `JELLYFIN_API_KEY` | Jellyfin API Key (**set securely via environment variable or Docker secret**) | `<set via env>` |
| `LOG_FILE` | Path to log file (inside container) | `/config/logs/jellyplex-sync.log` |
| `MOUNT_SOURCE` | Path to media library **on the host** | `/mnt/user/Media` |

**Important**: `MOUNT_SOURCE` must be the absolute path on your Unraid host, not the path inside the Radarr container (e.g., `/Cumflix`). This is because the script instructs the Docker daemon (running on the host) to mount this path.

**Security Note:**  
Never use hardcoded or published API keys. Always set `JELLYFIN_API_KEY` securely via environment variables or Docker secrets in your container configuration (e.g., Docker Compose, Unraid template). Do not commit or share your API key in documentation or code.
To set these in Radarr without editing the script, you would typically need to set them in the Radarr container's environment variables (e.g., in your Docker Compose or Unraid template).

## Troubleshooting

### Manual Test

You can manually test the script from inside the Radarr container to verify it works for a specific movie.

1.  **Exec into Radarr**:
    ```bash
    docker exec -it radarr /bin/bash
    ```

2.  **Run the script manually**:
    Export the required Radarr environment variables to simulate an event:

    ```bash
    export radarr_eventtype="Download"
    export radarr_movie_path="/Cumflix/movies/Avatar (2009)"
    export radarr_movie_title="Avatar"

    /config/scripts/jellyplex-direct-hook.sh
    ```

3.  **Verify Output**:
    *   Check the console output for "Sync completed successfully".
    *   Verify the movie files appeared in the Jellyfin folder (`/Cumflix/jellyfin/movies/Avatar (2009)`).
    *   Check `cat /config/logs/jellyplex-sync.log`.

### Common Issues

*   **Docker not found**: Ensure `/var/run/docker.sock` is mounted and the `docker` client is installed in the Radarr container.
*   **Permission Denied**: Check that the script is executable (`chmod +x`).
*   **Path not found**: Verify that `MOUNT_SOURCE` in the script matches your Radarr path mapping (default `/Cumflix`).
