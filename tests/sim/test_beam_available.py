from nbs_sim.beamline import Beamline


def test_beam_available_pv():
    ioc = Beamline(config={"devices": {}, "groups": {}, "roles": {}}, prefix="SIM:")
    pv = ioc.pvdb["SIM:beam_available"]
    assert pv.value == 1
