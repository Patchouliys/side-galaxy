# Local QEMU Experiments and Target Migration

Without a development board, you can first connect an ARM64 Linux VM to Side Galaxy. It receives experiment bundles, compiles and executes programs inside the guest, and returns logs and files through the same agent protocol. When a real Linux board becomes available, reuse the same bundle and plan with a different target.

## Start the Local Environment

The host needs Python 3.11+, uv, native core build dependencies, QEMU, and OpenSSH. Install QEMU on macOS:

```sh
brew install qemu
```

On Debian / Ubuntu hosts, install the ARM64 emulator and cloud-init seed tools:

```sh
sudo apt-get install qemu-system-arm qemu-utils qemu-efi-aarch64 cloud-image-utils openssh-client
```

Start the control service from the project directory:

```sh
uv sync --frozen
uv run sg serve --demo
```

In another terminal, create a local Linux experiment board:

```sh
uv run sg lab up
uv run sg lab status
```

The first launch downloads a pinned Debian 12 ARM64 cloud image, verifies its SHA-512, creates a separate writable overlay, starts the VM, and installs a toolchain, builds the platform's native library, and registers the agent inside the guest. Guest and physical-board deployment share the Python dependency versions and hashes pinned in `deploy/requirements.txt`. Later launches reuse the existing disk and board identity; platform source changes trigger an update to the guest installation.

Open the console and select the `QEMU` board in the device list. Built-in simulated devices still produce only synthetic data; the QEMU board uses the Linux execution module and actually runs uploaded code.

Defaults are 4 vCPUs, 2 GiB of memory, and a 16 GiB sparse disk. CPU 0 is reserved for management. Matching architectures use HVF on macOS or can use KVM on Linux; `--accel tcg` selects software emulation. QEMU management ports bind only to the local host, and the guest connects to the control service through a private SSH tunnel.

## Compile Your Own C Program

The repository includes a C example:

```sh
uv run sg pack examples/c-portability --output .data/c-portability.zip
uv run sg artifact-upload .data/c-portability.zip
```

Select the bundle and QEMU device in the console, set the experiment's memory budget and timeout, then preflight and run it. The setup step invokes the compiler inside the Linux guest; the run step executes the resulting program. The results page provides stdout, exit status, and declared output files.

Bundles can declare execution requirements in `requires`:

```json
{
  "architectures": ["aarch64"],
  "os": "linux",
  "commands": ["cc", "python3"]
}
```

Place this object in the `requires` field of `experiment.json`. Checks use information from the actual execution environment; the KVM module uses guest information. The platform checks once at admission, and the runner checks again before setup begins. Commands that still need installation should not be declared as existing prerequisites; the system image or deployment workflow should install them.

## Migrate to Real Devices

Follow the [deployment guide](operations.md) to register and install an agent on a real Linux board. Match the CPU architecture, distribution, and dependency versions between the guest and physical board where possible.

Select the target devices in the console, open a previous experiment, and choose "Reuse plan." The artifact digest, arguments, and environment variables are retained. Review the targets and resources, run preflight again, and submit.

The CLI can reuse an existing batch directly:

```sh
uv run sg replay SOURCE_BATCH_ID --boards TARGET_BOARD_ID --key deployment-001
```

`sg migrate` is an alias for the same command. MCP write mode provides `replay_experiment`. Use a new key for each new migration and reuse the original key when retrying the same request. The original batch and results remain intact; the new execution creates a new batch.

This migrates experiment programs and configuration, not a VM disk onto a Pi. Source bundles can be recompiled in the target environment; existing binaries must also match the target ABI and shared libraries. Architecture, OS, and command-existence checks catch common problems early, but drivers, device trees, peripherals, and timing behavior still depend on the target hardware.

## Multiple Environments and Offline Inputs

Give each lab its own directory and SSH port:

```sh
uv run sg lab up --state-dir .data/lab-second --ssh-port 22223
```

To supply your own image and platform source archive:

```sh
uv build --sdist
uv run sg lab up --image /path/to/linux-cloud.qcow2 --image-sha512 SHA512_DIGEST --source-archive dist/side_galaxy-0.1.0.tar.gz
```

The image needs cloud-init, OpenSSH, and a supported Linux userspace. `--arch x86_64` selects an x86_64 environment, `--firmware` specifies UEFI firmware, and `--wheelhouse` supplies Python dependency packages compatible with the guest architecture. Initial guest toolchain installation still needs access to package repositories unless the image already includes the toolchain.

## Stop the VM and Manage Local Files

Stop the VM after experiments finish:

```sh
uv run sg lab down
```

The disk and configuration are retained for the next `up`. After the VM stops, its platform device goes offline. Stopping a device during execution follows the existing task-loss and quarantine rules.

Image caches live in `.data/lab-images/`; default lab state lives in `.data/lab/`. These directories contain disks, private connection settings, and diagnostic logs and are excluded from Git.

[QEMU virt](https://www.qemu.org/docs/master/system/arm/virt.html) is a generic virtual-machine platform. [Debian cloud images](https://cloud.debian.org/images/cloud/bookworm/) provide the base system, and [NoCloud](https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html) provides first-boot configuration.
