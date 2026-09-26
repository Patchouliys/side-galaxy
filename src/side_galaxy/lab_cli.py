"""Local-only lab command setup, pinned image download, and source packaging."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import httpx


IMAGE_RELEASE = '20260923-2610'
IMAGE_HASHES = {
    'aarch64': ('arm64', '89a752d5c7d8e88bee39a57d88d496cca574f7d1e8df5df7a169825435f99feb11ed13ab27ec7bee96fe1584be4ff9479358fbca6cc859efa109f4aba18724c8'),
    'x86_64': ('amd64', '3d94c9dd66d8a283fde060b8810373b7ae04038b956ee00d553d1ae564f6fbdeaa2fd6e7404e87e53348b5a9509170f3ea7c0731ba737590c5c4cb8d559a47f8'),
}


def add_parser(sub):
    lab = sub.add_parser('lab', help='Start, inspect, or stop a local QEMU Linux target')
    commands = lab.add_subparsers(dest='lab_command', required=True)
    for name in ('up', 'status', 'down'):
        command = commands.add_parser(name)
        command.add_argument('--state-dir', default='.data/lab')
        if name != 'up': continue
        command.add_argument('--arch', choices=IMAGE_HASHES, default='aarch64')
        command.add_argument('--image', help='Local cloud image; requires --image-sha512')
        command.add_argument('--image-sha512')
        command.add_argument('--source-archive', help='Platform source distribution; otherwise build from this checkout')
        command.add_argument('--wheelhouse', help='Optional local directory of guest-compatible dependency wheels')
        command.add_argument('--qemu')
        command.add_argument('--qemu-img')
        command.add_argument('--firmware')
        command.add_argument('--accel', choices=['auto', 'hvf', 'kvm', 'tcg'], default='auto')
        command.add_argument('--cpus', type=int, default=4)
        command.add_argument('--memory-mib', type=int, default=2048)
        command.add_argument('--ssh-port', type=int, default=22222)
        command.add_argument('--disk-gib', type=int, default=16)
        command.add_argument('--timeout', type=int, default=900)


def image_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha512').hexdigest()


def default_image(arch, cache):
    variant, digest = IMAGE_HASHES[arch]
    name = f'debian-12-genericcloud-{variant}-{IMAGE_RELEASE}.qcow2'
    path = Path(cache) / name
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if image_digest(path) != digest: raise ValueError('Cached lab image checksum mismatch; replace the cached image')
        return path, digest
    url = f'https://cloud.debian.org/images/cloud/bookworm/{IMAGE_RELEASE}/{name}'
    print(f'Downloading verified Debian 12 {variant} lab image…', file=sys.stderr)
    partial = path.with_suffix('.partial')
    try:
        with httpx.stream('GET', url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            size = 0
            with partial.open('wb') as stream:
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > 4 * 1024**3: raise ValueError('Lab image exceeds download limit')
                    stream.write(chunk)
        if image_digest(partial) != digest: raise ValueError('Downloaded lab image checksum mismatch')
        partial.replace(path)
    except httpx.HTTPError as exc:
        raise ValueError('Lab image download failed; retry or supply a verified local image: ' + type(exc).__name__) from None
    return path, digest


def source_archive(state):
    root = Path(__file__).resolve().parents[2]
    if not (root / 'CMakeLists.txt').is_file() or not (root / 'pyproject.toml').is_file():
        raise ValueError('Supply --source-archive when running outside a Side Galaxy source checkout')
    if not shutil.which('uv'): raise ValueError('Install uv or supply --source-archive')
    state = Path(state).resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = state / 'source'
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    subprocess.run(['uv', 'build', '--sdist', '--out-dir', str(destination)], cwd=root,
                   stdout=sys.stderr, check=True, timeout=180)
    packages = sorted(destination.glob('side_galaxy-*.tar.gz'), key=lambda p: p.stat().st_mtime_ns)
    if not packages: raise ValueError('Source build did not produce a Side Galaxy distribution')
    return packages[-1]


def execute(args):
    from .lab import Lab
    lab = Lab(args.state_dir)
    if args.lab_command == 'status': return lab.status()
    if args.lab_command == 'down': return lab.down()
    if args.image:
        if not args.image_sha512 or not re.fullmatch('[a-fA-F0-9]{128}', args.image_sha512):
            raise ValueError('--image requires a 128-character --image-sha512 digest')
        image, digest = Path(args.image), args.image_sha512.lower()
    else:
        if args.image_sha512: raise ValueError('--image-sha512 requires --image')
        image, digest = default_image(args.arch, Path(args.state_dir).parent / 'lab-images')
    source = Path(args.source_archive) if args.source_archive else source_archive(args.state_dir)
    return lab.up(image=image, image_sha512=digest, source_archive=source, server=args.server,
                  token=os.environ.get('SG_TOKEN'), arch=args.arch, cpus=args.cpus,
                  memory_mib=args.memory_mib, ssh_port=args.ssh_port, disk_gib=args.disk_gib,
                  timeout=args.timeout, wheelhouse=args.wheelhouse, qemu=args.qemu,
                  qemu_img=args.qemu_img, firmware=args.firmware, accel=args.accel)
