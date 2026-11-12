import pytest

from nbs_sim import plugins
from nbs_sim.beamline import Beamline, select_process, sim_loaders
from nbs_sim.devices.signals import ConstantSignal
from nbs_sim.load import createIOCDevice
from nbs_sim.sdk import FixedBeam, SampleTable, beam_for

EMPTY = {"devices": {}, "groups": {}, "roles": {}}


class FakeEntryPoint:
    def __init__(self, name, obj):
        self.name = name
        self.value = f"fake:{name}"
        self.obj = obj

    def load(self):
        return self.obj


@pytest.fixture
def fake_entry_points(monkeypatch):
    groups = {}

    def entry_points(group):
        return groups.get(group, [])

    monkeypatch.setattr(plugins, "entry_points", entry_points)
    return groups


def test_loader_tables_merge_in_name_order(fake_entry_points):
    fake_entry_points[plugins.LOADERS] = [
        FakeEntryPoint("b", {"Shared": "b.Sim", "B": "b.B"}),
        FakeEntryPoint("a", lambda: {"Shared": "a.Sim", "A": "a.A"}),
    ]
    assert plugins.loader_table() == {"Shared": "b.Sim", "A": "a.A", "B": "b.B"}


def test_broken_loader_table_is_skipped(fake_entry_points):
    def broken():
        raise ImportError("missing dependency")

    fake_entry_points[plugins.LOADERS] = [
        FakeEntryPoint("bad", broken),
        FakeEntryPoint("good", {"A": "a.A"}),
    ]
    assert plugins.loader_table() == {"A": "a.A"}


def test_sim_conf_overrides_entry_points(fake_entry_points, tmp_path):
    fake_entry_points[plugins.LOADERS] = [
        FakeEntryPoint("pkg", {"Real": "pkg.Sim", "Other": "pkg.Other"}),
    ]
    conf = tmp_path / "sim_conf.toml"
    conf.write_text('[loaders]\n"Real" = "local.Sim"\n')
    assert sim_loaders(str(conf)) == {"Real": "local.Sim", "Other": "pkg.Other"}


def test_short_device_names(fake_entry_points):
    fake_entry_points[plugins.DEVICES] = [FakeEntryPoint("constant", ConstantSignal)]
    assert plugins.resolve("constant") is ConstantSignal
    assert plugins.resolve("nbs_sim.devices.signals.ConstantSignal") is ConstantSignal
    device = createIOCDevice("c", {"_target": "constant", "prefix": "T:c"})
    assert isinstance(device, ConstantSignal)


def test_select_process():
    config = {
        "i0": {"_target": "x"},
        "analyzer": {"_target": "y", "_process": "analyzer"},
        "camera": {"_target": "z", "_process": "camera"},
    }
    assert list(select_process(config)) == ["i0"]
    assert list(select_process(config, "analyzer")) == ["analyzer"]


def test_extra_process_falls_back_to_fixed_beam():
    main = Beamline(config=EMPTY, prefix="SIM:")
    extra = Beamline(config=EMPTY, prefix="SIM:", process="analyzer")
    assert main.computes_beam and not extra.computes_beam

    class Device:
        parent = extra
        beam_node = None

    assert isinstance(beam_for(Device()), FixedBeam)


def test_sample_table(tmp_path):
    (tmp_path / "samples.csv").write_text(
        "sample_id, sample_name, xps\ns1, gold, lines/au.toml\ns2, blank,\n"
    )
    table = SampleTable(str(tmp_path / "samples.csv"))
    assert table.get("s1", "sample_name") == "gold"
    assert table.path_for("s1", "xps") == str(tmp_path / "lines/au.toml")
    assert table.path_for("s2", "xps") is None
    assert table.get("nope", "xps") is None
