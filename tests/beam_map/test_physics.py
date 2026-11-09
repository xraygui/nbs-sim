import asyncio
import math
import tomllib
from types import SimpleNamespace

import pytest

from nbs_sim.beam_map import Input, MapError, load_map, parse_map, parse_overlay
from nbs_sim.beam_map.ioc import make_ioc
from nbs_sim.beam_map.mapfile import default_overlay
from nbs_sim.beam_map.physics import compute_physics
from nbs_sim.beam_map.status import compute_status

FE = "NBS_SIM:fe_shutter:Pos-Sts"
M1X = "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON"
BEAM = "NBS_SIM:beam_available"
RING = "NBS_SIM:Real-I"
M1T = "NBS_SIM:m1:Sim:Transmission"
MONO = "NBS_SIM:mono:Energy"

NOMINAL = {FE: 0, M1X: 15, BEAM: 1, RING: 400, M1T: 0.5, MONO: 500}


@pytest.fixture
def bmap(example_path, overlay_path):
    return load_map(example_path, overlay_path)


def physics(bmap, sim=False, **changes):
    values = {**NOMINAL, **changes}
    status = compute_status(bmap, values, sim)
    return compute_physics(bmap, status, values, sim)


def overlay(example_path, data):
    return parse_overlay(load_map(example_path), data)


# Parsing


def test_overlay_inputs(bmap):
    p = bmap.physics
    assert p.flux == Input(pv=RING, scale=2.0)
    assert p.transmission == {"m1": Input(pv=M1T)}
    assert p.energy == {"m1": Input(pv=MONO)}
    assert p.bandwidth == {"m1": Input(value=0.25), "branch2": Input(value=0.1)}
    assert {RING, M1T, MONO} <= bmap.input_pvs()


def test_map_without_overlay_has_no_physics(example_path):
    bmap = load_map(example_path)
    assert bmap.physics is None
    assert RING not in bmap.input_pvs()


@pytest.mark.parametrize(
    "data, message",
    [
        ({"nodes": {"nowhere": {"transmission": 1}}}, "not a node"),
        ({"nodes": {"m1": {"blocked_when": {"pv": FE, "eq": 1}}}}, "unknown key"),
        ({"map": {"name": "x"}}, "unknown key"),
        ({"beam": {"on_when": {"pv": BEAM, "eq": 1}}}, "unknown key"),
        ({"nodes": {"m1": {"energy": {"pv": MONO, "value": 1}}}}, "either pv or"),
        ({"nodes": {"m1": {"energy": {}}}}, "either pv or"),
        ({"nodes": {"m1": {"energy": {"value": 1, "scale": 2}}}}, "scale only"),
        ({"nodes": {"m1": {"energy": "500"}}}, "expected a number"),
    ],
)
def test_bad_overlay(example_path, data, message):
    with pytest.raises(MapError, match=message):
        overlay(example_path, data)


def test_bad_overlay_file_names_the_file(example_path, tmp_path):
    path = tmp_path / "bad.sim.toml"
    path.write_text('[nodes.nowhere]\ntransmission = 1\n')
    with pytest.raises(MapError, match="bad.sim.toml"):
        load_map(example_path, str(path))


def test_source_is_a_reserved_node_name(example_path):
    with open(example_path, "rb") as f:
        data = tomllib.load(f)
    data["nodes"]["Source"] = {"upstream": "m1"}
    with pytest.raises(MapError, match="reserved"):
        parse_map(data)


def test_default_overlay(tmp_path):
    path = tmp_path / "beam_map.toml"
    path.write_text("")
    assert default_overlay(str(path)) is None
    (tmp_path / "beam_map.sim.toml").write_text("")
    assert default_overlay(str(path)) == str(tmp_path / "beam_map.sim.toml")


# Computing


def test_flux_down_the_tree(bmap):
    phys, source = physics(bmap)
    assert source == 800
    assert phys["front_end"].flux == 800
    assert phys["m1"].flux == 800
    assert phys["m1"].transmission == 0.5
    assert phys["branch1"].flux == 400
    assert phys["branch1"].transmission == 1
    # An unselected branch gets the beam but stops it.
    assert phys["branch2"].flux == 400
    assert phys["branch2"].transmission == 0


def test_blocking_is_zero_transmission(bmap):
    phys, source = physics(bmap, **{FE: 1})
    assert source == 800
    assert phys["front_end"].flux == 800
    assert phys["front_end"].transmission == 0
    assert phys["m1"].flux == 0
    assert phys["branch1"].flux == 0


def test_beam_off_means_no_flux(bmap):
    phys, source = physics(bmap, **{BEAM: 0})
    assert source == 0
    assert all(p.flux == 0 for p in phys.values())


def test_energy_and_bandwidth_pass_downstream(bmap):
    phys, _ = physics(bmap, **{MONO: 750})
    assert math.isnan(phys["front_end"].energy)
    assert phys["front_end"].bandwidth == 0
    assert phys["m1"].energy == 750
    assert phys["m1"].bandwidth == 0.25
    assert phys["branch1"].energy == 750
    assert phys["branch1"].bandwidth == 0.25
    # The nearest node that sets a value wins.
    assert phys["branch2"].bandwidth == 0.1


def test_transmission_is_clipped(bmap):
    phys, _ = physics(bmap, **{M1T: 1.5})
    assert phys["m1"].transmission == 1
    phys, _ = physics(bmap, **{M1T: -0.2})
    assert phys["m1"].transmission == 0


def test_disconnected_inputs(bmap):
    gone = {RING: None, M1T: None, MONO: None}
    phys, source = physics(bmap, sim=False, **gone)
    assert source == 0
    assert phys["m1"].transmission == 0
    assert math.isnan(phys["branch1"].energy)
    phys, source = physics(bmap, sim=True, **gone)
    assert source == 0  # nothing to ignore it in favour of
    assert phys["m1"].transmission == 1
    assert math.isnan(phys["branch1"].energy)


def test_nan_input_counts_as_disconnected(bmap):
    phys, _ = physics(bmap, sim=False, **{M1T: float("nan")})
    assert phys["m1"].transmission == 0


def test_no_flux_input_means_unit_source(example_path):
    bmap = overlay(example_path, {"nodes": {"m1": {"transmission": 0.25}}})
    phys, source = physics(bmap)
    assert source == 1
    assert phys["branch1"].flux == 0.25


# The IOC


def test_ioc_without_overlay_serves_only_status(example_path):
    ioc = make_ioc(load_map(example_path), sim=True)
    suffixes = {name.rsplit(":", 1)[1] for name in ioc.pvdb}
    assert suffixes == {"MapName", "Blocking", "PathClear", "BeamExpected", "Reason"}


def test_ioc_updates_physics_pvs(bmap):
    ioc = make_ioc(bmap)
    pvdb = ioc.pvdb

    async def run():
        for pv, value in NOMINAL.items():
            await ioc.handle(pv, SimpleNamespace(data=[value]))
        assert pvdb["NBS_MAP:Source:Flux"].value == 800
        assert pvdb["NBS_MAP:branch1:Flux"].value == 400
        assert pvdb["NBS_MAP:branch1:Energy"].value == 500
        await ioc.handle(M1T, SimpleNamespace(data=[0.25]))
        assert pvdb["NBS_MAP:m1:Transmission"].value == 0.25
        assert pvdb["NBS_MAP:branch1:Flux"].value == 200

    asyncio.run(run())
