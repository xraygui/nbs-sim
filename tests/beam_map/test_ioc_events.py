"""Event handling in the map IOC, without a network."""

import asyncio
from types import SimpleNamespace

from nbs_sim.beam_map import load_map
from nbs_sim.beam_map.ioc import make_ioc

FE = "NBS_SIM:fe_shutter:Pos-Sts"


def value_event(data):
    return SimpleNamespace(data=data)


def test_bad_value_fails_safe_and_monitoring_continues(example_path):
    ioc = make_ioc(load_map(example_path))

    async def run():
        await ioc.handle(FE, value_event([0]))
        assert ioc.values[FE] == 0.0
        # An empty update must not stop monitoring; the PV counts as unknown.
        await ioc.handle(FE, value_event([]))
        assert ioc.values[FE] is None
        assert ioc.status["front_end"].blocking is True
        await ioc.handle(FE, value_event([1]))
        assert ioc.values[FE] == 1.0

    asyncio.run(run())


def test_disconnect_event(example_path):
    ioc = make_ioc(load_map(example_path))

    async def run():
        await ioc.handle(FE, value_event([0]))
        await ioc.handle(FE, "disconnected")
        assert ioc.values[FE] is None

    asyncio.run(run())
