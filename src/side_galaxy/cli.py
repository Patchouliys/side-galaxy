import argparse
import io
import stat
import zipfile
import json
import os
from pathlib import Path
import signal
import sys
import time
import uuid

from .client import Client
from .models import Enrollment, Plan


def output(value): print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sg", description="Side Galaxy · modular board experiments")
    parser.add_argument("--server", default=os.environ.get("SG_SERVER", "http://127.0.0.1:7980"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--demo", action="store_true")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=7980)
    serve.add_argument("--db", default=".data/galaxy.db")
    serve.add_argument('--lab-state-dir', action='append', help='Managed QEMU state directory; repeat for multiple labs')
    workspace = sub.add_parser('workspace', help='Inspect or change demonstration mode')
    workspace.add_argument('--demo', choices=['on', 'off'])
    sub.add_parser('labs', help='List managed QEMU instances and restart operations')
    sub.add_parser("boards")
    sub.add_parser("profiles")
    sub.add_parser("batches")
    sub.add_parser("artifacts")
    sub.add_parser('environments', help='List offline prepared guest packages')
    env_pack = sub.add_parser('environment-pack', help='Pack a prepared guest environment')
    env_pack.add_argument('directory')
    env_pack.add_argument('--output', required=True)
    env_upload = sub.add_parser('environment-upload', help='Upload a prepared environment ZIP')
    env_upload.add_argument('bundle')
    logs = sub.add_parser('logs', help='Read incremental experiment output')
    logs.add_argument('run')
    logs.add_argument('--after', type=int, default=0)
    logs.add_argument('--follow', action='store_true')
    pack = sub.add_parser("pack")
    pack.add_argument("directory")
    pack.add_argument("--output", required=True)
    upload = sub.add_parser("artifact-upload", aliases=["upload"])
    upload.add_argument("bundle")
    download = sub.add_parser("output")
    download.add_argument("run")
    download.add_argument("index", type=int)
    download.add_argument("--output", required=True)
    for name in ("preflight", "submit"):
        p = sub.add_parser(name)
        p.add_argument("plan", help="JSON file or - for stdin")
        p.add_argument("--enqueue", action="store_true", help="Wait fairly for targets instead of rejecting occupancy")
        if name == "submit": p.add_argument("--key", required=True, help="Stable idempotency key; reuse on retry")
    for name in ("batch", "cancel", "reload", "recover"):
        p = sub.add_parser(name)
        p.add_argument("id")
        if name == "recover": p.add_argument("--cleanup-confirmed", action="store_true")
        if name == 'reload': p.add_argument('--force', action='store_true', help='Interrupt current work before module validation')
    replay = sub.add_parser("replay", aliases=["migrate"])
    replay.add_argument("id", help="Source batch ID")
    replay.add_argument("--boards", nargs="+", required=True, help="Replacement target board IDs")
    replay.add_argument("--key", required=True, help="New idempotency key for the replay")
    from .lab_cli import add_parser as add_lab_parser
    add_lab_parser(sub)
    enroll = sub.add_parser("enroll")
    enroll.add_argument("--name", required=True)
    enroll.add_argument("--board-profile", default="generic")
    enroll.add_argument("--system-profile", default="linux-process")
    enroll.add_argument("--output", required=True, help="Private new agent config file (0600)")
    agent = sub.add_parser("agent")
    agent.add_argument("--config", required=True)
    agent.add_argument("--state-dir", default=".data/agent")
    agent.add_argument("--module-file", help="Trusted local standalone Python module")
    agent.add_argument("--profiles-dir", help="Additional boards/ and systems/ manifest directories")
    mcp = sub.add_parser("mcp")
    mcp.add_argument("--allow-writes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "lab":
            from .lab_cli import execute
            output(execute(args))
            return
        if args.command == 'environment-pack':
            from .environments import pack_environment
            output(pack_environment(args.directory, args.output))
            return
        if args.command == "pack":
            from .workload_runner import validate_bundle, MAX_BUNDLE, MAX_EXPANDED
            root = Path(args.directory).resolve(strict=True)
            if not root.is_dir(): raise ValueError("Pack requires an experiment directory")
            target = Path(args.output).resolve()
            if target.exists(): raise ValueError("Output already exists")
            ignored = {".git", ".env", ".ssh", ".aws", ".venv", "node_modules", "__pycache__", ".data", ".cache"}
            buffer = io.BytesIO()
            count, expanded = 0, 0
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for current, dirs, files in os.walk(root, followlinks=False):
                    dirs[:] = sorted(d for d in dirs if d not in ignored and not Path(current, d).is_symlink())
                    for name in sorted(files):
                        path = Path(current, name)
                        if name in ignored or name.startswith(".env.") or name.endswith((".pem", ".key")): continue
                        if path.is_symlink(): raise ValueError("Symlinks are not supported in experiment packages")
                        if path.resolve() == target: continue
                        info = path.lstat()
                        if not stat.S_ISREG(info.st_mode): raise ValueError("Only regular experiment files can be packed")
                        expanded += info.st_size
                        if expanded > MAX_EXPANDED or count >= 512: raise ValueError("Experiment exceeds expanded size or file limits")
                        archive.write(path, path.relative_to(root).as_posix())
                        count += 1
                        if buffer.tell() > MAX_BUNDLE or count > 512: raise ValueError("Experiment package exceeds limits")
            data = buffer.getvalue()
            manifest = validate_bundle(data)
            with target.open("xb") as stream: stream.write(data)
            output({"packed": True, "files": count, "size": len(data), "manifest": manifest})
            return
        if args.command == "serve":
            if args.demo and args.host not in ("127.0.0.1", "::1", "localhost"):
                parser.error("--demo must bind to loopback")
            import uvicorn
            from .api import create_app
            app = create_app(args.db, args.demo, os.environ.get("SG_TOKEN"), os.environ.get("SG_READ_TOKEN"),
                             local_access=args.host in ('127.0.0.1', '::1', 'localhost') and not os.environ.get('SG_TOKEN'),
                             lab_dirs=args.lab_state_dir)
            uvicorn.run(app, host=args.host, port=args.port, access_log=False)
            return
        if args.command == "mcp":
            from .mcp_server import create_mcp
            os.environ["SG_SERVER"] = args.server
            create_mcp(args.allow_writes).run(transport="stdio")
            return
        if args.command == "agent":
            from .runtime import Agent, Modules
            config = Path(args.config)
            if config.stat().st_mode & 0o077: raise ValueError("Agent config must be private: chmod 600")
            data = json.loads(config.read_text())
            client = Client(data["server"], data["agent_token"])
            modules = Modules(args.state_dir, data["board_profile"], data["system_profile"], args.profiles_dir, args.module_file)
            runner = Agent(client, data["board_id"], modules)
            def shutdown(signum, frame): raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, shutdown)
            last_ok = time.monotonic()
            try:
                while True:
                    try:
                        runner.tick()
                        last_ok = time.monotonic()
                    except Exception as exc:
                        print("Agent connection or protocol error: " + type(exc).__name__, file=sys.stderr)
                        if runner.execution:
                            if time.monotonic() - last_ok > 20: runner.execution.stop()
                            completed = runner.execution.poll()
                            if completed:
                                runner.pending = (runner.execution.job["id"], completed)
                                runner.execution = None
                    time.sleep(1)
            except KeyboardInterrupt:
                runner.shutdown()
            finally: client.http.close()
            return
        client = Client(args.server)
        try:
            if args.command == 'workspace':
                output(client.request('PUT', '/api/workspace', {'demo': args.demo == 'on'}) if args.demo else client.request('GET', '/api/workspace'))
            elif args.command == 'labs': output(client.request('GET', '/api/labs'))
            elif args.command in ("boards", "profiles", "batches", "artifacts", "environments"):
                output(client.request("GET", "/api/" + ("catalog" if args.command == "profiles" else args.command)))
            elif args.command == 'environment-upload': output(client.upload_environment(args.bundle))
            elif args.command == 'logs':
                if args.after < 0: raise ValueError('Log cursor must be nonnegative')
                cursor = args.after
                try:
                    while True:
                        result = client.request('GET', f'/api/runs/{args.run}/logs?after={cursor}')
                        if not args.follow:
                            output(result)
                            break
                        for event in result['events']:
                            print(event['text'], end='', file=sys.stderr if event['stream'] == 'stderr' else sys.stdout, flush=True)
                        if result['truncated']: print('[live logs truncated]', file=sys.stderr)
                        cursor = result['next_sequence']
                        time.sleep(1)
                except KeyboardInterrupt: pass
            elif args.command in ("artifact-upload", "upload"):
                from .workload_runner import MAX_BUNDLE, validate_bundle
                with Path(args.bundle).open("rb") as stream: data = stream.read(MAX_BUNDLE + 1)
                validate_bundle(data)
                output(client.upload_artifact(data))
            elif args.command == "output":
                data = client.download_output(args.run, args.index)
                with Path(args.output).open("xb") as stream: stream.write(data)
                output({"saved": True, "size": len(data)})
            elif args.command in ("preflight", "submit"):
                text = sys.stdin.read() if args.plan == "-" else Path(args.plan).read_text()
                plan = Plan.model_validate_json(text)
                output(client.request("POST", ("/api/preflight" if args.command == "preflight" else "/api/batches") + ("?enqueue=true" if args.enqueue else ""), plan.model_dump(), getattr(args, "key", None)))
            elif args.command == "batch": output(client.request("GET", "/api/batches/" + args.id))
            elif args.command in ("replay", "migrate"):
                output(client.request("POST", f"/api/batches/{args.id}/replay", {"boards": args.boards}, args.key))
            elif args.command == "cancel": output(client.request("POST", "/api/batches/" + args.id + "/cancel"))
            elif args.command in ("reload", "recover"):
                suffix = "?cleanup_confirmed=true" if getattr(args, "cleanup_confirmed", False) else ""
                if args.command == 'reload' and args.force: suffix = '?force=true'
                output(client.request("POST", f"/api/boards/{args.id}/{args.command}" + suffix))
            elif args.command == "enroll":
                # Reserve private output before creating a board; never overwrite existing credentials.
                fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as stream:
                    record = Enrollment(name=args.name, board_profile=args.board_profile, system_profile=args.system_profile)
                    result = client.request("POST", "/api/boards", record.model_dump())
                    json.dump({**result, "server": args.server, "board_profile": args.board_profile, "system_profile": args.system_profile}, stream, indent=2)
                output({"board_id": result["board_id"], "config_saved": True})
        finally: client.http.close()
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__": sys.exit(main())
