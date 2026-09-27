# Supervised local services

The local `sg service` commands register the controller and an optional USB/SSH transport with the operating system's service manager. macOS uses user LaunchAgents; Linux uses user systemd units. The manager restarts an unexpectedly exited process. These operations are available only through the local CLI, not through HTTP or MCP host-shell endpoints.

## Controller

Stop an existing foreground controller when its experiments are idle, then install the service using the same database:

```sh
uv run sg service install controller --db .data/galaxy.db --port 7980 --state-dir .data/services
uv run sg service status --state-dir .data/services
```

Installation starts the service and configures startup with the user session. The controller listens only on `127.0.0.1`. If authentication is configured, supply the existing `SG_TOKEN` and `SG_READ_TOKEN` in the installing shell's environment. The generated private service definition preserves those selected values; status output never includes them.

The recorded Python executable must belong to an installed Side Galaxy environment. Keep that environment and checkout available while the service is installed. Service state paths and database paths are resolved when installing; subsequent commands must use the same `--state-dir`.

Installing the same settings is idempotent. To change settings, first uninstall the idle service and then install the replacement. The database and private diagnostic files remain in place.

## USB/SSH transport

Install the paired controller first. Use an existing private OpenSSH configuration containing the board's host alias, user and authentication settings:

```sh
uv run sg service install tunnel \
  --ssh-config "$HOME/.ssh/side-galaxy/config" \
  --ssh-host experiment-board \
  --local-port 7980 --remote-port 17980 \
  --state-dir .data/services
```

The SSH configuration and private keys must have mode `0600`, with their containing private directory set to `0700`. Use paths accessible to the service account, such as `~/.ssh/side-galaxy` or a private application-support directory. macOS privacy controls can prevent a background OpenSSH service from reading files in Documents or Desktop even when an interactive terminal can read them. Provision service credentials in the normal private service location instead of changing privacy protections; the installer does not copy credentials automatically. The tunnel exposes the controller to the board at `http://127.0.0.1:17980` through a reverse forwarding bound to the board's loopback address. Its fixed argument list uses non-interactive authentication and requires forwarding setup to succeed. It does not run a remote shell. The connection has its own process rather than sharing an interactive SSH control socket.

When the device disconnects, SSH keepalive detection ends the transport process and the native manager retries. Once the USB connection and SSH service return, the same definition reconnects. The board does not need Internet access.

## Status and lifecycle

```sh
uv run sg service status controller --state-dir .data/services
uv run sg service restart controller --state-dir .data/services
uv run sg service stop tunnel --state-dir .data/services
uv run sg service start tunnel --state-dir .data/services
uv run sg service uninstall tunnel --state-dir .data/services
uv run sg service uninstall controller --state-dir .data/services
```

Status reports `installed`, supervisor registration, `running`, and controller `reachable` separately. A process can be running while `/healthz` is unavailable. Tunnel `reachable` is null: its process state alone does not prove the remote application is ready. Missing service-manager access is reported separately from an unavailable controller endpoint. Status does not return executable paths, database paths, SSH aliases, environment variables or credentials.

Intentional stop, restart and uninstall operations reject waiting, queued, running or cancelling experiments. The database writer lock remains held while the service is stopped, preventing a new admission from racing the idle check. Automatic supervisor restart remains available after a crash. A lost or quarantined run still requires its normal evidence-backed recovery; restarting the controller does not release that state.

Uninstall the tunnel before uninstalling its paired controller. `stop` affects the current service session; `uninstall` removes the managed definition and its future automatic startup. It keeps the controller database and local logs.

On Linux, user services normally follow the user session. For operation without an interactive login, an administrator can enable that account's systemd lingering policy. On macOS, these are login-session LaunchAgents; a machine-wide service is a separate administrator deployment.

## Private configuration

Keep service state under an ignored directory such as `.data/services`. State and native definitions are written atomically with mode `0600`; the state directory uses `0700`. The native service identity includes a hash of the canonical state directory so separate development configurations do not overwrite each other's definitions. Service commands never accept arbitrary executable arguments or uploaded unit files.

The Linux restart behavior follows the [systemd service specification](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml). macOS definitions use the built-in `launchctl` bootstrap, print and bootout operations.
