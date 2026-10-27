import pytest

from nbs_sim.beam_map import load_map, parse_map
from nbs_sim.beam_map.status import NodeStatus, compute_status

FE = "NBS_SIM:fe_shutter:Pos-Sts"
M1X = "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON"
BEAM = "NBS_SIM:beam_available"


@pytest.fixture
def bmap(example_path):
    return load_map(example_path)


def test_shutter_closed(bmap):
    st = compute_status(bmap, {FE: 1, M1X: 15, BEAM: 1})
    reason = f"front_end blocked: {FE} = 1"
    assert st["front_end"] == NodeStatus(True, True, False, reason)
    for name in ["m1", "branch1", "branch2"]:
        assert st[name].path_clear is False
        assert st[name].beam_expected is False
    assert st["m1"].reason == reason
    assert st["branch1"].reason == reason
    # branch2 names its own, closer, blocker so it stays visible
    assert st["branch2"].reason == f"branch2 not selected: {M1X} = 15"


def test_branch_selection(bmap):
    st = compute_status(bmap, {FE: 0, M1X: 15, BEAM: 1})
    assert st["front_end"] == NodeStatus(False, True, True, "")
    assert st["m1"] == NodeStatus(False, True, True, "")
    assert st["branch1"] == NodeStatus(False, True, True, "")
    assert st["branch2"] == NodeStatus(
        True, True, False, f"branch2 not selected: {M1X} = 15"
    )


def test_selection_follows_shared_pv(bmap):
    st = compute_status(bmap, {FE: 0, M1X: -15, BEAM: 1})
    assert st["branch1"].beam_expected is False
    assert st["branch2"].beam_expected is True


def test_beam_off(bmap):
    st = compute_status(bmap, {FE: 0, M1X: 15, BEAM: 0})
    assert st["branch1"] == NodeStatus(False, True, False, f"beam off: {BEAM} = 0")
    # a blocking node still names itself, not the beam
    assert st["branch2"].reason == f"branch2 not selected: {M1X} = 15"


def test_unselected_blocks_descendants(example_path):
    import tomllib

    with open(example_path, "rb") as f:
        data = tomllib.load(f)
    data["nodes"]["branch2_child"] = {"upstream": "branch2"}
    st = compute_status(parse_map(data), {FE: 0, M1X: 15, BEAM: 1})
    child = st["branch2_child"]
    assert child.path_clear is False
    assert child.blocking is False
    assert child.reason == f"branch2 not selected: {M1X} = 15"


def test_closest_blocker_wins(example_path):
    import tomllib

    with open(example_path, "rb") as f:
        data = tomllib.load(f)
    data["nodes"]["branch2_child"] = {"upstream": "branch2"}
    st = compute_status(parse_map(data), {FE: 1, M1X: 15, BEAM: 1})
    assert st["branch2_child"].reason == f"branch2 not selected: {M1X} = 15"


def test_disconnected_fail_safe(bmap):
    st = compute_status(bmap, {M1X: 15, BEAM: 1})
    assert st["front_end"].blocking is True
    assert st["front_end"].reason == f"front_end: {FE} disconnected"
    st = compute_status(bmap, {FE: 0, M1X: None, BEAM: 1})
    assert st["branch1"].blocking and st["branch2"].blocking
    assert st["branch1"].reason == f"branch1: {M1X} disconnected"
    st = compute_status(bmap, {FE: 0, M1X: 15})
    assert st["branch1"].reason == f"beam off: {BEAM} disconnected"


def test_sim_mode_ignores_disconnected(bmap):
    st = compute_status(bmap, {}, sim=True)
    for name, s in st.items():
        assert s == NodeStatus(False, True, True, ""), name


def test_sim_mode_still_uses_connected_pvs(bmap):
    st = compute_status(bmap, {FE: 1}, sim=True)
    assert st["m1"].reason == f"front_end blocked: {FE} = 1"


def test_no_beam_section():
    bmap = parse_map({"map": {"prefix": "T:"}, "nodes": {"a": {}}})
    assert compute_status(bmap, {})["a"] == NodeStatus(False, True, True, "")


def test_multiple_roots():
    bmap = parse_map(
        {
            "nodes": {
                "a": {"blocked_when": {"pv": "A", "eq": 1}},
                "b": {},
                "a2": {"upstream": "a"},
                "b2": {"upstream": "b"},
            }
        }
    )
    st = compute_status(bmap, {"A": 1})
    assert st["a"].path_clear is True
    assert st["a2"].path_clear is False
    assert st["b2"].beam_expected is True


def test_fractional_value_in_reason(bmap):
    st = compute_status(bmap, {FE: 0, M1X: 9.5, BEAM: 1})
    assert st["branch1"].reason == f"branch1 not selected: {M1X} = 9.5"
