import pytest

from nbs_sim.beam_map import MapError, load_map, parse_map
from nbs_sim.beam_map.mapfile import Condition


def base(**nodes):
    return {"map": {"name": "t", "prefix": "T:"}, "nodes": nodes}


def test_load_example(example_path):
    bmap = load_map(example_path)
    assert bmap.prefix == "NBS_MAP:"
    assert list(bmap.nodes) == ["front_end", "m1", "branch1", "branch2"]
    assert bmap.nodes["branch1"].upstream == "m1"
    assert bmap.children("m1") == ["branch1", "branch2"]
    assert bmap.ancestors("branch2") == ["m1", "front_end"]
    assert bmap.input_pvs() == {
        "NBS_SIM:beam_available",
        "NBS_SIM:fe_shutter:Pos-Sts",
        "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON",
    }


def test_between_inclusive_and_unordered():
    cond = Condition("X", "between", (-10, -20))
    assert cond.holds(-10)
    assert cond.holds(-20)
    assert cond.holds(-15)
    assert not cond.holds(-21)
    assert not cond.holds(-9.99)


@pytest.mark.parametrize(
    "op, true_at, false_at",
    [
        ("eq", 1, 2),
        ("ne", 2, 1),
        ("lt", 0, 1),
        ("le", 1, 2),
        ("gt", 2, 1),
        ("ge", 1, 0),
    ],
)
def test_ops(op, true_at, false_at):
    cond = Condition("X", op, 1)
    assert cond.holds(true_at)
    assert not cond.holds(false_at)


def test_blocked_when_list():
    bmap = parse_map(
        base(v={"blocked_when": [{"pv": "A", "eq": 1}, {"pv": "B", "gt": 0}]})
    )
    assert [c.pv for c in bmap.nodes["v"].blocked_when] == ["A", "B"]


def test_no_beam_section_means_no_conditions():
    assert parse_map(base(a={})).beam_on == []


@pytest.mark.parametrize(
    "nodes, words",
    [
        ({"a": {"upstream": "nope"}}, ["a", "upstream", "nope"]),
        ({"a": {"upstream": "b"}, "b": {"upstream": "a"}}, ["cycle"]),
        ({"a": {"upsteam": "b"}}, ["a", "upsteam"]),
        ({"a": {"blocked_when": {"pv": "X", "eq": 1, "gt": 0}}}, ["a", "blocked_when"]),
        ({"a": {"blocked_when": {"pv": "X"}}}, ["a", "blocked_when"]),
        ({"a": {"selected_when": {"pv": "X", "between": [1]}}}, ["a", "between"]),
        ({"a": {"selected_when": {"eq": 1}}}, ["a", "pv"]),
    ],
)
def test_bad_maps(nodes, words):
    with pytest.raises(MapError) as err:
        parse_map(base(**nodes))
    for word in words:
        assert word in str(err.value)


def test_unknown_top_level_key():
    data = base(a={})
    data["bean"] = {}
    with pytest.raises(MapError, match="bean"):
        parse_map(data)
