#!/bin/bash
set -e

# --- CONFIGURATION ---
MOUNT_POINT="/scratch-data"
CONTAINERD_CONFIG="/etc/containerd/config.toml"
LEMONADE_SERVICE="/etc/systemd/system/lemonade.service"

echo "Step 1: Identifying NVMe Disk..."
# Find first NVMe with no partitions and no mountpoint
TARGET_DISK=$(lsblk -dnox NAME,MOUNTPOINT,TYPE | awk '$2=="" && $3=="disk" {print "/dev/"$1}' | grep nvme | head -n 1)

if [ -z "$TARGET_DISK" ]; then
    echo "No unmounted NVMe disk found. Checking if already mounted..."
    if ! mountpoint -q "$MOUNT_POINT"; then
        echo "Error: No disk found and $MOUNT_POINT is not mounted."
        exit 1
    fi
else
    echo "Found disk: $TARGET_DISK. Preparing filesystem..."
    if ! blkid "$TARGET_DISK" > /dev/null 2>&1; then
        mkfs.ext4 -m 0 -E lazy_itable_init=0,lazy_journal_init=0 "$TARGET_DISK"
    fi
    mkdir -p "$MOUNT_POINT"
    mount "$TARGET_DISK" "$MOUNT_POINT"
fi

# Create sub-directories for the services
mkdir -p "$MOUNT_POINT/containerd"
mkdir -p "$MOUNT_POINT/huggingface"

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