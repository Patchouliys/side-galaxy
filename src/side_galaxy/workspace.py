"""Serialized sample-agent lifecycle; persistent admission policy stays native."""
from pathlib import Path
from threading import RLock

from .models import Enrollment
from .runtime import Agent, LocalClient, Modules


def synthetic(board):
    return bool(board.get('local') or board.get('system_profile') == 'simulator'
                or (board.get('description') or {}).get('mode') == 'synthetic')


class Workspace:
    def __init__(self, store, demo=False):
        self.store = store
        self.agents = []
        self.lock = RLock()
        self.set_demo(demo)

    def set_demo(self, enabled):
        with self.lock:
            self.store.set_workspace_mode(enabled)
            if not enabled:
                self._stop()
            elif not self.agents:
                existing = {b['id']: b for b in self.store.boards()}
                try:
                    for board_id, name, profile in [('pi4-lab', 'PI 4 - ORION', 'pi4'), ('pi5-lab', 'PI 5 - LYRA', 'pi5'), ('pi5-edge', 'PI 5 - CYGNUS', 'pi5')]:
                        if board_id not in existing:
                            self.store.enroll(Enrollment(name=name, board_profile=profile, system_profile='simulator'), local=True, board_id=board_id)
                        elif not existing[board_id].get('local'):
                            raise ValueError('Sample identity belongs to a non-local device')
                        agent = Agent(LocalClient(self.store), board_id,
                                      Modules(Path(self.store.path).parent / 'modules' / board_id, profile, 'simulator'))
                        self.agents.append(agent)
                        agent.tick()
                except Exception:
                    self.store.set_workspace_mode(False)
                    self._stop()
                    raise
            return self.store.workspace_mode()

    def tick(self):
        with self.lock:
            for agent in self.agents:
                try: agent.tick()
                except Exception: pass  # Native heartbeat expiry retains uncertain leases.
            self.store.boards()

    def _stop(self):
        for agent in self.agents: agent.shutdown()
        self.agents.clear()

    def shutdown(self):
        with self.lock: self._stop()

    def boards(self):
        boards = self.store.boards()
        return boards if self.store.workspace_mode()['demo'] else [b for b in boards if not synthetic(b)]

    def batches(self):
        return self.store.batches(real_only=not self.store.workspace_mode()['demo'])
