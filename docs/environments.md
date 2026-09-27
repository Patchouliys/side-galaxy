# Offline experiment environments

Side Galaxy sends a prepared guest environment and a separate experiment bundle to an execution target. The target needs no Internet access. QEMU boots the guest with a fresh writable overlay, transfers the experiment through QEMU Guest Agent, and removes the overlay after the managed QEMU process has stopped. The physical board stays running.

This workflow reuses the image-and-run model of container tools while using a separate guest kernel. Packages are Side Galaxy VM environments, not OCI images. Install QEMU and `qemu-img` administratively before enrolling a target with the `qemu-environment` system profile. On Linux, the agent account needs access to `/dev/kvm`; missing access fails instead of silently falling back to emulation.

## Prepare an image centrally

Prepare a Linux guest containing Python 3.11 or later, QEMU Guest Agent, and every compiler, library, input dataset, or tool the experiment needs. Enable QEMU Guest Agent at boot on `/dev/virtio-ports/org.qemu.guest_agent.0`. Its policy must permit `guest-ping`, `guest-exec`, `guest-exec-status`, and guest file open/read/write/close operations. The guest kernel must support the virtio disk and serial devices and Python's Linux process identity helpers (`pidfd_open` and `pidfd_send_signal`).

The package architecture must match the target: `aarch64` or `x86_64`. A prepared QEMU `virt` guest can run on different ARM64 boards with KVM; a physical board's vendor boot disk is not automatically compatible with the QEMU machine. Use `console=ttyAMA0` for the ARM64 serial console or `console=ttyS0` for x86.

A direct-boot source directory contains:

```text
environment.json
rootfs.raw
kernel
initrd              # optional when the kernel can mount the root disk itself
```

Example source manifest (the pack operation fills `files` with SHA-256 digests):

```json
{
  "schema": 1,
  "name": "arm64-experiment-tools",
  "architecture": "aarch64",
  "disk": {"file": "rootfs.raw", "format": "raw"},
  "boot": {
    "kernel": "kernel",
    "initrd": "initrd",
    "cmdline": "console=ttyAMA0 root=/dev/vda rw"
  },
  "runtime": {
    "os": "linux",
    "commands": ["python3", "cc", "make"],
    "commands_complete": false
  },
  "files": {}
}
```

Use the correct `root=` value for the image: `/dev/vda` for a raw filesystem or, for example, `/dev/vda2` for a partitioned disk. As an alternative to direct kernel boot, include `firmware.fd` and set `boot` to `{"firmware":"firmware.fd"}`. The firmware and root disk must be a compatible boot pair.

An uploaded package contains exact file hashes. Only the declared files and `environment.json` are permitted; directories, symbolic links, special files, duplicate entries, unknown names, encrypted ZIP entries, and traversal paths are rejected. The transfer limit is 2 GiB and the expanded limit is 8 GiB. The base disk is always interpreted explicitly as RAW; qcow2 base images and external backing chains are not accepted. Convert images centrally with `qemu-img convert -O raw` before packaging.

The optional `runtime` is an operator-declared guest contract used during admission. It describes the image, not the physical host. After boot, the module probes the actual guest and checks the declaration; experiment command requirements are also checked by the guest runner.

## Publish through the platform

Package the prepared directory, upload it once, and list available versions:

```sh
uv run sg environment-pack prepared-environment --output .data/environment.zip
uv run sg environment-upload .data/environment.zip
uv run sg environments
```

Set the returned digest as `environment_sha256` alongside the experiment's `artifact_sha256` in a workload plan, or select the image in the console. Agent transfer verifies the digest and populates a local cache. Later runs reuse the cached base and create a new writable overlay.

## Run and reset

Select an uploaded environment and an experiment artifact in the workload plan. Choose available host CPUs, guest RAM, arguments, and the duration. Leave interference CPUs empty: an uploaded experiment owns its commands. A VM receives one virtual CPU per selected CPU, and its host process inherits the selected CPU affinity on Linux. QEMU RAM is the requested guest RAM; QEMU host overhead is additional.

Each run has its own UUID, QMP socket, QGA socket, and qcow2 overlay backed by the verified immutable RAW base. No guest network or host shared directory is exposed. Guest files transfer over the local virtio serial channel; no SSH login is required inside the environment.

Starting another run resets all guest writes by creating a new overlay. Cancellation requests stop the workload and managed VM. QMP checks the instance UUID before requesting shutdown; a process handle permits terminating the exact child if QMP is unavailable. Overlay deletion happens only after process exit is confirmed. Unconfirmed cleanup retains state and prevents automatic resource reuse.

Results include the environment digest, instance UUID, actual accelerator, guest runtime, CPU affinity when available, a bounded console tail, workload output, and VM cleanup evidence. Console output and guest workload stdout/stderr are also forwarded as bounded running log events. Guest events use a size-limited file tailed through QEMU Guest Agent; truncation is reported independently of final result capture. On Linux, the default accelerator is KVM. Administrator-selected `SG_QEMU_ACCEL=tcg` explicitly enables emulation; macOS uses HVF by default. Reported modes remain distinct (`qemu-kvm`, `qemu-tcg`, `qemu-hvf`).

Store private image binaries, enrollment data, host-specific configuration, and deployment evidence in ignored local state. Share source manifests and generic image preparation recipes through Git.
