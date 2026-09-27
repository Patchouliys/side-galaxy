"""Local service management arguments; no service control is exposed over HTTP."""
from .services import ServiceManager


def add_parser(sub):
    service = sub.add_parser('service', help='Manage local supervised controller and SSH tunnel services')
    actions = service.add_subparsers(dest='service_action', required=True)
    install = actions.add_parser('install')
    kinds = install.add_subparsers(dest='service_kind', required=True)
    controller = kinds.add_parser('controller')
    controller.add_argument('--db', default='.data/galaxy.db')
    controller.add_argument('--port', type=int, default=7980)
    controller.add_argument('--lab-state-dir', action='append', help='Managed QEMU state directory; repeat for multiple labs')
    controller.add_argument('--state-dir', default='.data/services')
    tunnel = kinds.add_parser('tunnel')
    tunnel.add_argument('--ssh-config', required=True)
    tunnel.add_argument('--ssh-host', required=True)
    tunnel.add_argument('--local-port', type=int, default=7980)
    tunnel.add_argument('--remote-port', type=int, default=17980)
    tunnel.add_argument('--state-dir', default='.data/services')
    for action in ('status', 'start', 'stop', 'restart', 'uninstall'):
        command = actions.add_parser(action)
        command.add_argument('service_kind', choices=['controller', 'tunnel'], nargs='?' if action == 'status' else None)
        command.add_argument('--state-dir', default='.data/services')


def execute(args):
    manager = ServiceManager(args.state_dir)
    if args.service_action == 'status': return manager.status(args.service_kind)
    if args.service_action == 'install':
        if args.service_kind == 'controller': return manager.install_controller(args.db, args.port, args.lab_state_dir)
        return manager.install_tunnel(args.ssh_config, args.ssh_host, args.local_port, args.remote_port)
    return manager.action(args.service_kind, args.service_action)
