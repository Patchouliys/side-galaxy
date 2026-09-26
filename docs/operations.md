# Operation, Deployment, and AI Integration

## Local Demo

```sh
uv sync --frozen
uv run sg serve --demo
```

Open `http://127.0.0.1:7980`. The three simulated Pi boards and their metrics are labeled synthetic. Demo mode listens only on loopback and needs no physical development boards. Do not expose this mode to the public internet.

```sh
uv run sg boards
uv run sg preflight examples/pi-contention.json
uv run sg submit examples/pi-contention.json --key first-experiment
uv run sg batches
uv run sg batch BATCH_ID
uv run sg cancel BATCH_ID
```

Reuse the key when retrying the same submission; choose a new key for a new experiment. Preflight does not reserve boards, and submission repeats checks atomically. Each board has one experiment lease. Built-in experiments support victim/interferer roles internally; custom bundles organize their own workloads. Synchronized starts across boards are not guaranteed. The batch list shows the most recent 100 batches; older records remain accessible by ID.

## Single Server

```sh
export SG_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SG_READ_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run sg serve --host 127.0.0.1 --db .data/galaxy.db
```

Keep tokens in restricted local secret storage, not in commits, command-line arguments, or URLs. Use a reverse proxy for HTTPS and forward request Host / Origin correctly to the backend. `SG_READ_TOKEN` is for read-only AI access; the operator token permits submission, cancellation, registration, and recovery. Each control server uses a pair of operator / read tokens, while each board agent holds a separate token.

Alternatively, set the same environment variables and run `docker compose up --build -d`; the service is exposed only on localhost. The Dockerfile excludes development directories, credentials, and local data. Dependencies are exported from `uv.lock` and verified by hash. The container does not perform hardware KVM operations; board agents run on Linux hosts. Running containers requires a Docker engine.

API documentation is at the server's `/docs`. API endpoints include `/api/catalog`, `boards`, `preflight`, and `batches`. POST `/api/batches` requires `Idempotency-Key`. Automatic demo agents apply only to sample boards; ordinary registration still requires per-board credentials.

## Registration and Multi-Board Deployment

First configure SG_SERVER / SG_TOKEN on the control machine, then create a private configuration for each board. `--output` does not overwrite existing files.

```sh
mkdir -p .data
export SG_SERVER=https://galaxy.example.com
uv run sg enroll --name pi4-lab --board-profile pi4 --system-profile linux-kvm --output .data/pi4-agent.json
uv run sg enroll --name pi5-lab --board-profile pi5 --system-profile linux-kvm --output .data/pi5-agent.json
```

Package the application on the control machine:

```sh
uv build
```

Copy `deploy/inventory.example.yml` to the ignored `deploy/inventory.local.yml` and fill in actual addresses, SSH users, dedicated VM names, private configuration paths, and the wheel path. After configuring the local inventory, run:

```sh
ansible-playbook -i deploy/inventory.local.yml deploy/agents.yml
```

The example uses RFC 5737 reserved IP addresses, not reachable devices. The control machine needs Ansible; initial deployment requires SSH and sudo access. The playbook installs Python, the agent, and a systemd service, and may download packages over the network. It does not install a hypervisor, create a VM, or reboot the board. Redeployment restarts the agent, so wait until no tasks are running. Use hot reload for routine module updates to avoid restarting the agent.

This Ansible playbook uses apt and systemd and applies to Debian-family Linux. Other systems need corresponding installation tasks. See [module development](modules.md) for extending board and system profiles.

## Pi + KVM Configuration

1. Confirm a 64-bit system, Python >=3.11, `/dev/kvm`, and kernel KVM support are available.
2. Install and verify libvirt, then run a dedicated experiment VM. Give the galaxy service account permission to manage only that VM; the deployment script does not automatically grant broad libvirt administration rights.
3. Set `SG_KVM_DOMAIN` to the VM; `SG_LIBVIRT_URI` defaults to `qemu:///system`. The service template supplies the domain name; configure other environment variables through a local service override.
4. Verify that `virsh domstate DOMAIN` / `virsh vcpupin DOMAIN --live` are readable. Save the original affinity first.
5. Wait for `sg boards` to show ready and `kvm-affinity`. Replace the board ID in `examples/kvm-affinity.json`, then preflight and submit.
6. Inspect the domain UUID, affinity_before/applied/restored, cleanup_ok, and boot ID in the result to check the execution target, resource restoration, and host boot state.

Linux process experiments use the `linux-process` system profile, with process affinity and RLIMIT_AS resource limits. Built-in microbenchmarks divide the memory budget among workers, with at least 64 MiB per worker. `workload` bundles use a per-process address-space limit, with `memory_mib` of at least 128. Python runtimes may need a larger budget. See [Linux / KVM execution](kvm-workloads.md) for precise semantics.

## MCP

Configure any compatible MCP stdio client, with command pointing to the installed `sg`:

```json
{"mcpServers":{"side-galaxy":{"command":"sg","args":["mcp"],"env":{"SG_SERVER":"https://galaxy.example.com","SG_TOKEN":"SUPPLY_READ_TOKEN_VIA_SECRET_STORAGE"}}}}
```

Default tools are list_boards, list_profiles, list_artifacts, preflight, get_batch, and get_output. If the task explicitly authorizes AI to operate experiment devices, change to `args:["mcp","--allow-writes"]` and use an operator token. This adds upload_artifact, run_experiment, cancel_batch, and reload_module. Enabling MCP write tools does not bypass server authorization, admission, or version checks. The token placeholder cannot establish a connection as written.

## Operations

Deployment uses one uvicorn process, a single SQLite writer, and one server. A heartbeat missing for 30 seconds or a task exceeding its deadline triggers lost/quarantine state. Experiments with unknown state are not automatically rerun. After disconnection, the agent attempts to stop local experiments and submits a terminal state when the network returns. If the server has already marked a run lost, that state remains until manual verification and recovery.

Stop the service or use the SQLite backup API when backing up `.data/galaxy.db`; do not copy only the main database file while a WAL is active. Databases, module snapshots, credentials, and experiment outputs should not enter public Git history.

Experiment code is delivered through artifact upload and per-board download; see [workloads.md](workloads.md) for the full workflow. Target images provide Python, compilers, and system dependencies for Linux/KVM guests. Manifest setup steps may install dependencies permitted in the environment, with logs retained on failure. See [kvm-workloads.md](kvm-workloads.md) for additional KVM guest requirements.
