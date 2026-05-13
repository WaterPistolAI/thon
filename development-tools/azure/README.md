## Ephemeral NVMe & Service Orchestration Setup

This setup automates the discovery, formatting, and mounting of Azure ephemeral NVMe disks. It also dynamically reconfigures **Containerd** and the **Lemonade Server** to use this high-speed storage for heavy workloads (image layers and HuggingFace models) before the services start.

---

## 🛠 Components

1. **`bootstrap-ephemeral.sh`**: The worker script that identifies the raw NVMe, mounts it to `/scratch-data`, and updates service configurations.
2. **`ephemeral-setup.service`**: A systemd unit that ensures the script runs at boot time *after* the hardware is ready but *before* Docker, Containerd, or Lemonade start.

---

## 🚀 Installation

### 1. Create the Mount Point and Bootstrap Script

Create the mountpoint at `/scratch-data`:

```bash
sudo mkdir /scratch-data

```

Create the script at `/usr/local/bin/bootstrap-ephemeral.sh`:

```bash
sudo cp bootstrap-ephemeral.sh /usr/local/bin/bootstrap-ephemeral.sh

```

**Make the scritpt executable:**

```bash
sudo chmod +x /usr/local/bin/bootstrap-ephemeral.sh

```

### 2. Create the Systemd Service

Create the service file to manage the boot order:

```bash
sudo cp ephemeral-setup.service /etc/systemd/system/ephemeral-setup.service

```

### 3. Enable the Automation

Reload the systemd daemon and enable the service so it triggers on every reboot:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ephemeral-setup.service

```

---

## 📂 Configuration Details

### How it handles the NVMe

The script uses `lsblk` to find the first disk that is an **NVMe** type, has **no partitions**, and **no mountpoint**. This prevents it from accidentally touching your OS disk or existing persistent data disks.

### Service Modifications

* **Containerd**: Updates `root = "/scratch-data/containerd"` in `/etc/containerd/config.toml`.
* **Lemonade**: Injects `Environment="HF_HOME=/scratch-data/huggingface"` into the `[Service]` section of your lemonade systemd unit.
* **Docker**: Remains on the OS disk (by default) to ensure your container instances and configurations persist, while their heavy underlying layers are offloaded to the ephemeral disk via Containerd.

---

## 🔍 Verification & Troubleshooting

After a reboot, you can verify the setup with these commands:

* **Check the Mount:**
`df -h | grep /scratch-data`
* **Check Service Order:**
`systemctl status ephemeral-setup.service`
*(Look for "Active: active (exited)" and no error messages in the logs)*
* **Verify Containerd Root:**
`grep "root =" /etc/containerd/config.toml`
* **Verify Lemonade Environment:**
`systemctl show lemonade.service --property=Environment`

---

## ⚠️ Important Notes

* **Data Volatility**: Anything stored in `/scratch-data` **will be lost** if the Azure instance is Deallocated or Stopped. This setup is intended only for caches (HuggingFace models) and transient data (Containerd layers).
* **Manual Run**: You can manually trigger the setup without rebooting by running `sudo systemctl start ephemeral-setup.service`, but you should stop the Docker and Lemonade services first to avoid file-in-use errors.