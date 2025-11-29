#!/bin/bash

IMAGE="ghcr.io/plex-migration-homelab/jellyplex-sync"
VERSION="latest"

# Pull the latest version of the image from the registry
docker pull $IMAGE:$VERSION

# Get the full SHA256 ID of the current image
CURRENT_ID=$(docker images --no-trunc --quiet $IMAGE:$VERSION)

# Find and remove any older versions of the same image
docker images --no-trunc --format "{{.Repository}} {{.ID}}" \
    | awk -v img="$IMAGE" -v curr="$CURRENT_ID" '$1 == img && $2 != curr { print $2 }' \
    | while read -r image_id; do
        echo "Removing old image: $image_id"
        docker rmi "$image_id"
    done

# Execute jellyplex-sync with mounted media directory
# NOTE: Adjust the paths below to match your actual media directories!
docker run --rm -v /mnt/user/media:/mnt $IMAGE:$VERSION \
    --delete --create --dry-run /mnt/Movies /mnt/Plex
