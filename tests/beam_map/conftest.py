import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Keep the test IOCs off the default CA ports and search only on loopback, so
# they can't see or be seen by any real IOC on this machine. The servers bind
# all interfaces because a socket bound to 127.0.0.1 misses loopback
# broadcasts.
CA_ENV = {
    "EPICS_CA_AUTO_ADDR_LIST": "NO",
    "EPICS_CA_ADDR_LIST": "127.255.255.255",
    "EPICS_CAS_BEACON_ADDR_LIST": "127.255.255.255",
    "EPICS_CA_SERVER_PORT": "25064",
    "EPICS_CA_REPEATER_PORT": "25065",
}
os.environ.update(CA_ENV)

HERE = Path(__file__).parent
SRC = HERE.parents[1] / "src"

EXAMPLE = Path(__file__).parent / "example_map.toml"
OVERLAY = Path(__file__).parent / "example_overlay.toml"


@pytest.fixture
def example_path():
    return str(EXAMPLE)


@pytest.fixture
def overlay_path():
    return str(OVERLAY)


def _spawn(args, extra_env=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.pop("NBS_SIM_MODE", None)
    env.update(extra_env or {})
    return subprocess.Popen(
        [sys.executable, *args],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class Procs:
    """Start and stop the fake input IOC and the map IOC."""

    def __init__(self):
        self.inputs = None
        self.map_ioc = None

    def start_inputs(self):
        self.inputs = _spawn([str(HERE / "fake_inputs.py")])

    def stop_inputs(self):
        self.inputs.terminate()
        self.inputs.wait(5)

    def start_map_ioc(self, *extra, env=None):
        self.map_ioc = _spawn(
            ["-m", "nbs_sim.beam_map.ioc", "--map", str(EXAMPLE), *extra], env
        )

    def stop_all(self):
        for p in (self.inputs, self.map_ioc):
            if p is not None and p.poll() is None:
                p.terminate()
                p.wait(5)


@pytest.fixture
def procs():
    p = Procs()
    yield p
    p.stop_all()


@pytest.fixture(scope="session")
def ca():
    from caproto.threading.client import Context

    return Context()


def wait_for(fn, timeout=10.0):
    """Poll fn until it returns truthy; return its last value."""
    end = time.monotonic() + timeout
    while True:
        try:
            value = fn()
        except Exception:
            value = None
        if value or time.monotonic() > end:
            return value
        time.sleep(0.1)
