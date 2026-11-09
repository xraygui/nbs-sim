import asyncio
import math

import pytest

from nbs_sim.beam_map import parse_map
from nbs_sim.beamline import Beamline
from nbs_sim.devices.detectors import GenericDetector
from nbs_sim.load import createIOCDevice
from nbs_sim.sdk import BeamInput, FixedBeam, ParentBeam, beam_for

EMPTY = {"devices": {}, "groups": {}, "roles": {}}
MAP = parse_map({"map": {"prefix": "TESTMAP:"}, "nodes": {"es": {}}})


class Device:
    def __init__(self, parent=None, beam_node=None):
        self.parent = parent
        self.beam_node = beam_node


def test_fixed_beam():
    beam = FixedBeam(flux=2.0, energy=300.0, bandwidth=0.1)
    assert (beam.flux(), beam.energy(), beam.bandwidth(300)) == (2.0, 300.0, 0.1)


def test_parent_beam_is_the_old_computation():
    bl = Beamline(config=EMPTY, prefix="SIM:")
    beam = ParentBeam(bl)
    assert beam.flux() == pytest.approx(bl.intensity_func(), rel=0.01)
    assert beam.bandwidth(500) == 0.0


def test_beam_for_picks_a_source():
    bl = Beamline(config=EMPTY, prefix="SIM:")
    assert isinstance(beam_for(Device()), FixedBeam)
    assert isinstance(beam_for(Device(bl, "es")), ParentBeam)  # no beam map
    mapped = Beamline(config=EMPTY, prefix="SIM:", beam_map=MAP)
    assert isinstance(beam_for(Device(mapped)), ParentBeam)  # no node
    device = Device(mapped, "es")
    beam = beam_for(device)
    assert isinstance(beam, BeamInput)
    assert beam.pvname("Flux") == "TESTMAP:es:Flux"
    assert isinstance(beam.fallback, ParentBeam)
    assert beam_for(device) is beam


def test_beam_input_prefers_the_map():
    beam = BeamInput("M:", "es", fallback=FixedBeam(flux=1.0, energy=250.0, bandwidth=0.5))
    assert not beam.connected
    assert beam.flux() == 1.0
    beam.values.update(Flux=40.0, Energy=float("nan"), Bandwidth=0.2)
    assert beam.connected
    assert beam.flux() == 40.0
    assert beam.energy() == 250.0  # NaN: the map does not set it here
    assert beam.bandwidth(250.0) == 0.2


def test_mean_flux():
    beam = BeamInput("M:", "es")
    beam._record(100.0, t=0.0)
    beam._record(0.0, t=5.0)
    assert beam.mean_flux(0.0, 10.0) == pytest.approx(50.0)
    assert beam.mean_flux(5.0, 10.0) == pytest.approx(0.0)
    assert beam.mean_flux(2.5, 7.5) == pytest.approx(50.0)
    # Before the history starts: the current flux.
    beam.values["Flux"] = 7.0
    assert beam.mean_flux(-5.0, 1.0) == 7.0


def test_loader_sets_the_node():
    bl = Beamline(config=EMPTY, prefix="SIM:", beam_map=MAP)
    info = {"_target": "nbs_sim.devices.detectors.GenericDetector",
            "_node": "es", "prefix": "SIM:i0:", "kind": "i0"}
    dev = createIOCDevice("i0", info, parent=bl)
    assert dev.beam_node == "es"


def test_detector_reads_the_map_flux():
    bl = Beamline(config=EMPTY, prefix="SIM:", beam_map=MAP)
    det = GenericDetector("SIM:i0:", kind="i0", parent=bl)
    det.beam_node = "es"

    async def run():
        beam = beam_for(det)
        beam._task = asyncio.get_running_loop().create_future()  # no network
        beam.values["Flux"] = 12.5
        return await det._read()

    assert asyncio.run(run()) == 12.5


def test_ref_detector_uses_the_map_bandwidth():
    bl = Beamline(config=EMPTY, prefix="SIM:", beam_map=MAP)
    det = GenericDetector("SIM:ref:", kind="ref", parent=bl)
    det.beam_node = "es"
    peak = 285.0

    async def signal(bandwidth):
        beam = beam_for(det)
        beam._task = asyncio.get_running_loop().create_future()
        beam.values.update(Flux=1.0, Energy=peak, Bandwidth=bandwidth)
        return await det._read()

    sharp = asyncio.run(signal(0.0))
    broad = asyncio.run(signal(2.0))
    assert not math.isclose(sharp, broad)
