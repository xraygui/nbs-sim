from nbs_sim.beamline import Beamline


def test_beam_available_pv():
    ioc = Beamline(config={"devices": {}, "groups": {}, "roles": {}}, prefix="SIM:")
    pv = ioc.pvdb["SIM:beam_available"]
    assert pv.value == 1


def test_beam_dump_empties_ring():
    ioc = Beamline(config={"devices": {}, "groups": {}, "roles": {}}, prefix="SIM:")
    assert 450 <= ioc.current_func() <= 500
    ioc.beam_available._data["value"] = 0
    assert ioc.current_func() == 0.0
    assert ioc.intensity_func() == 0.0


def test_ring_current_device_from_sim_conf():
    from nbs_sim.load import createIOCDevice
    from nbs_sim.devices.signals import RingCurrent

    ioc = Beamline(config={"devices": {}, "groups": {}, "roles": {}}, prefix="SIM:")
    info = {"_target": "nbs_sim.devices.signals.RingCurrent", "prefix": "NBS_SIM:Real-I"}
    dev = createIOCDevice("ring_current", info, parent=ioc)
    assert isinstance(dev, RingCurrent)
    assert "NBS_SIM:Real-I" in ioc.pvdb
