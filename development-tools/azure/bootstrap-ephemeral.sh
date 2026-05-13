#!/bin/bash
set -e

# --- CONFIGURATION ---
MOUNT_POINT="/scratch-data"
VOLUME_LABEL="scratch-data"
CONTAINERD_CONFIG="/etc/containerd/config.toml"
LEMONADE_SERVICE="/usr/lib/systemd/system/lemond.service"

mkdir -p "$MOUNT_POINT"

echo "Step 1: Identifying NVMe Disk..."

# 1. Look for NVMe disks that have NO partitions
# Empty MOUNTPOINT fields cause awk field-shifting with whitespace-delimited lsblk output,
# so we query disk names and partition checks separately.
TARGET_DISK=""
for disk in $(lsblk -ndo NAME,TYPE | awk '$2=="disk" && $1 ~ /nvme/ {print $1}'); do
    if ! lsblk -nlo TYPE "/dev/$disk" 2>/dev/null | grep -q "part"; then
        TARGET_DISK="/dev/$disk"
        break
    fi
done

# Validation and Fallback
if [ -z "$TARGET_DISK" ]; then
    if mountpoint -q "$MOUNT_POINT"; then
        echo "Disk is already mounted at $MOUNT_POINT."
    else
        echo "Error: Could not find an unpartitioned, unmounted NVMe disk."
        exit 1
    fi
else
    echo "Found raw ephemeral disk: $TARGET_DISK"
    if ! blkid "$TARGET_DISK" > /dev/null 2>&1; then
        mkfs.ext4 -m 0 -E lazy_itable_init=0,lazy_journal_init=0 -L "$VOLUME_LABEL" "$TARGET_DISK"
    elif ! blkid "$TARGET_DISK" -s LABEL -o value | grep -q "$VOLUME_LABEL"; then
        e2label "$TARGET_DISK" "$VOLUME_LABEL"
    fi
    mkdir -p "$MOUNT_POINT"
    mount "$TARGET_DISK" "$MOUNT_POINT"

    if ! grep -q "LABEL=$VOLUME_LABEL" /etc/fstab; then
        echo "LABEL=$VOLUME_LABEL $MOUNT_POINT ext4 defaults,noatime,nofail 0 2" >> /etc/fstab
        echo "Added fstab entry: LABEL=$VOLUME_LABEL -> $MOUNT_POINT"
    fi
fi

# Create sub-directories for the services
mkdir -p "$MOUNT_POINT/containerd"
mkdir -p "$MOUNT_POINT/huggingface"

# Grant Lemonade ownership of Hugging Face hub models
chown lemonade:lemonade "$MOUNT_POINT/huggingface"

echo "Step 2: Configuring Containerd..."
if [ -f "$CONTAINERD_CONFIG" ]; then
    # Use sed to find the 'root =' line and update it to the scratch path
    # This regex looks for the line starting with root and replaces the path
    if grep -q "^root =" "$CONTAINERD_CONFIG"; then
        sed -i "s|^root =.*|root = \"$MOUNT_POINT/containerd\"|" "$CONTAINERD_CONFIG"
    else
        # If the root line doesn't exist, prepend it to the top
        sed -i "1i root = \"$MOUNT_POINT/containerd\"" "$CONTAINERD_CONFIG"
    fi
else
    # Create a basic config if it doesn't exist
    echo "root = \"$MOUNT_POINT/containerd\"" > "$CONTAINERD_CONFIG"
fi

echo "Step 3: Configuring Lemonade (HF_HOME)..."
if [ -f "$LEMONADE_SERVICE" ]; then
    # Check if HF_HOME is already set
    if grep -q "HF_HOME=" "$LEMONADE_SERVICE"; then
        sed -i "s|HF_HOME=[^[:space:]\"]*|HF_HOME=$MOUNT_POINT/huggingface|" "$LEMONADE_SERVICE"
    else
        # Insert the Environment variable under the [Service] section
        sed -i "/^\[Service\]/a Environment=\"HF_HOME=$MOUNT_POINT/huggingface\"" "$LEMONADE_SERVICE"
    fi
    systemctl daemon-reload
else
    echo "Warning: $LEMONADE_SERVICE not found. Skipping Lemonade config."
fi

echo "Automation Complete. Ready for service start."