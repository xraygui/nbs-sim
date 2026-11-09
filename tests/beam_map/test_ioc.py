from caproto import ChannelType
from conftest import wait_for

FE = "NBS_SIM:fe_shutter:Pos-Sts"
M1X = "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON"


def read(ca, name):
    (pv,) = ca.get_pvs(name, timeout=1)
    resp = pv.read(timeout=1)
    if resp.data_type == ChannelType.CHAR:
        return bytes(resp.data).rstrip(b"\0").decode()
    return resp.data[0]


def write(ca, name, value):
    (pv,) = ca.get_pvs(name, timeout=1)
    pv.write([value], wait=True, timeout=2)


def equals(ca, name, value):
    return lambda: read(ca, name) == value


def test_status_follows_inputs(procs, ca):
    procs.start_inputs()
    procs.start_map_ioc()
    assert wait_for(equals(ca, "NBS_MAP:branch1:BeamExpected", 1))
    write(ca, FE, 1)
    assert wait_for(equals(ca, "NBS_MAP:front_end:Blocking", 1))
    assert wait_for(
        lambda: "front_end blocked" in read(ca, "NBS_MAP:m1:Reason"), timeout=3
    )
    assert read(ca, "NBS_MAP:m1:PathClear") == 0


def test_shared_pv_updates_both_branches(procs, ca):
    procs.start_inputs()
    procs.start_map_ioc()
    assert wait_for(equals(ca, "NBS_MAP:branch1:BeamExpected", 1))
    write(ca, M1X, -15.0)
    assert wait_for(equals(ca, "NBS_MAP:branch2:BeamExpected", 1), timeout=3)
    assert read(ca, "NBS_MAP:branch1:BeamExpected") == 0


def test_reason_longer_than_40_chars(procs, ca):
    procs.start_inputs()
    procs.start_map_ioc()
    expected = f"branch2 not selected: {M1X} = 15"
    assert len(expected) > 40
    assert wait_for(equals(ca, "NBS_MAP:branch2:Reason", expected))


def test_input_ioc_restart(procs, ca):
    procs.start_inputs()
    procs.start_map_ioc()
    assert wait_for(equals(ca, "NBS_MAP:branch1:BeamExpected", 1))
    procs.stop_inputs()
    assert wait_for(
        lambda: read(ca, "NBS_MAP:front_end:Reason").endswith("disconnected"),
        timeout=20,
    )
    assert read(ca, "NBS_MAP:branch1:BeamExpected") == 0
    procs.start_inputs()
    assert wait_for(equals(ca, "NBS_MAP:branch1:BeamExpected", 1), timeout=20)


def test_sim_mode_no_inputs(procs, ca):
    procs.start_map_ioc("--sim")
    assert wait_for(equals(ca, "NBS_MAP:branch1:BeamExpected", 1))
    assert read(ca, "NBS_MAP:branch2:BeamExpected") == 1


def test_sim_mode_from_env(procs, ca):
    procs.start_map_ioc(env={"NBS_SIM_MODE": "1"})
    assert wait_for(equals(ca, "NBS_MAP:front_end:BeamExpected", 1))


def test_status_pvs_are_read_only(procs, ca):
    procs.start_map_ioc("--sim")
    assert wait_for(equals(ca, "NBS_MAP:branch1:BeamExpected", 1))
    (pv,) = ca.get_pvs("NBS_MAP:branch1:BeamExpected", timeout=1)
    try:
        pv.write([0], wait=True, timeout=2)
    except Exception:
        pass
    assert read(ca, "NBS_MAP:branch1:BeamExpected") == 1


def test_physics_pvs_follow_inputs(procs, ca, overlay_path):
    procs.start_inputs()
    procs.start_map_ioc("--sim", "--sim-overlay", overlay_path)
    assert wait_for(equals(ca, "NBS_MAP:branch1:Flux", 400.0))
    assert read(ca, "NBS_MAP:Source:Flux") == 800.0
    assert read(ca, "NBS_MAP:branch1:Energy") == 500.0
    assert read(ca, "NBS_MAP:branch1:Bandwidth") == 0.25
    write(ca, "NBS_SIM:Real-I", 100.0)
    assert wait_for(equals(ca, "NBS_MAP:branch1:Flux", 100.0), timeout=3)
    write(ca, FE, 1)
    assert wait_for(equals(ca, "NBS_MAP:branch1:Flux", 0.0), timeout=3)
    assert read(ca, "NBS_MAP:front_end:Transmission") == 0.0
    # The status PVs are unchanged by the overlay.
    assert read(ca, "NBS_MAP:front_end:Blocking") == 1


def test_overlay_needs_sim_mode(procs, overlay_path):
    procs.start_map_ioc("--sim-overlay", overlay_path)
    assert procs.map_ioc.wait(30) == 2
