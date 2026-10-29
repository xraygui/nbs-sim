import asyncio

from nbs_sim.beamline import Beamline
from nbs_sim.devices.shutters import SSTShutter
from nbs_sim.devices.vacuum import InterlockedGateValve, VacuumGauge
from nbs_sim.load import createIOCDevice


def make_ioc():
    ioc = Beamline(config={"devices": {}, "groups": {}, "roles": {}}, prefix="SIM:")
    gauge = createIOCDevice("ig_es", {"_target": "nbs_sim.devices.vacuum.VacuumGauge",
                                      "prefix": "T:ig_es:", "base": 1e-8}, parent=ioc)
    valve = createIOCDevice("gv_es", {"_target": "nbs_sim.devices.vacuum.InterlockedGateValve",
                                      "prefix": "T:gv_es:", "gauge": "ig_es", "trip_above": 1e-6,
                                      "openval": 0, "closeval": 1}, parent=ioc)
    ioc.devices.update(ig_es=gauge, gv_es=valve)
    return ioc, gauge, valve


def test_gauge_reads_its_base_with_jitter():
    _, gauge, _ = make_ioc()
    readings = [gauge.reading() for _ in range(200)]
    assert all(0.7e-8 < r < 1.3e-8 for r in readings)
    assert "T:ig_es:P:Raw-I" in gauge.pvdb and "T:ig_es:P:Sim-SP" in gauge.pvdb


def test_valve_trips_above_the_level_and_refuses_to_open():
    ioc, gauge, valve = make_ioc()

    async def run():
        await gauge.pressure.write(value=1e-8)
        await valve.check_interlock()
        assert valve.state.value == 0 and valve.interlock.value == 0
        await gauge.pressure.write(value=2e-6)
        await valve.check_interlock()
        assert valve.state.value == 1 and valve.transmission.value == 0 and valve.interlock.value == 1
        await valve.opn.write(1)
        assert valve.state.value == 1
        # Recovered pressure leaves it closed until it is opened
        await gauge.pressure.write(value=1e-8)
        await valve.check_interlock()
        assert valve.state.value == 1 and valve.interlock.value == 0
        await valve.opn.write(1)
        assert valve.state.value == 0 and valve.transmission.value == 1

    asyncio.run(run())


def test_shutter_open_command_is_untouched():
    assert InterlockedGateValve.opn is not SSTShutter.opn
