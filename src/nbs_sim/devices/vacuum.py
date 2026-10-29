"""
Vacuum gauges and gate valves interlocked to them.

No pressure dynamics: a gauge reads its base pressure with a few percent of
jitter. Writing the base (``P:Sim-SP``) stands in for a vacuum fault, and an
interlocked gate valve closes when its gauge reads above the trip level.
"""

import numpy as np
from caproto.server import PVGroup, pvproperty

from .shutters import SSTShutter


class VacuumGauge(PVGroup):
    """
    Gauge reading a fixed base pressure in Torr.

    Parameters
    ----------
    prefix : str
        PV prefix.
    base : float
        Normal pressure in Torr.
    jitter : float
        Relative scatter of each reading.
    """

    pressure = pvproperty(value=1e-8, dtype=float, read_only=True, name="P:Raw-I", units="Torr", precision=3)
    base = pvproperty(value=1e-8, dtype=float, name="P:Sim-SP", units="Torr", precision=3,
                      doc="Sim only: the pressure the gauge reads; raise it to fake a vacuum fault")

    def __init__(self, prefix, base=1e-8, jitter=0.05, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self._jitter = jitter
        self.base._data["value"] = float(base)
        self.pressure._data["value"] = float(base)

    def reading(self):
        """The current reading, as the scan writes it."""
        base = float(self.base.value)
        return max(base * (1 + self._jitter * np.random.randn()), 0.0)

    @pressure.scan(period=1.0)
    async def pressure(self, instance, async_lib):
        await instance.write(value=self.reading())


class InterlockedGateValve(SSTShutter):
    """
    Gate valve that the EPS closes while a gauge reads above ``trip_above``.

    It stays closed after the pressure recovers until someone opens it, and an
    open command is ignored while the gauge is still above the trip level.

    Parameters
    ----------
    prefix : str
        PV prefix.
    gauge : str
        Device key of the gauge, looked up on the parent beamline.
    trip_above : float
        Trip pressure in Torr.
    """

    interlock = pvproperty(value=0, dtype=int, read_only=True, name="Intlk-Sts",
                           doc="1 while the gauge is above the trip level")
    # Redefined, not decorated, so SSTShutter's own open command is unchanged
    opn = pvproperty(value=0, dtype=int, name="Cmd:Opn-Cmd")

    def __init__(self, prefix, gauge=None, trip_above=1e-6, parent=None, **kwargs):
        super().__init__(prefix, parent=parent, **kwargs)
        self._gauge = gauge
        self._trip_above = float(trip_above)

    def tripped(self):
        """Whether the gauge reads above the trip level now."""
        if self._gauge is None or self.parent is None:
            return False
        gauge = getattr(self.parent, "devices", {}).get(self._gauge)
        if gauge is None:
            return False
        return float(gauge.pressure.value) > self._trip_above

    @interlock.scan(period=0.5)
    async def interlock(self, instance, async_lib):
        await self.check_interlock()

    async def check_interlock(self):
        """Close the valve while the gauge is above the trip level."""
        tripped = self.tripped()
        if tripped and self.state.value != self._closeval:
            await self.state.write(value=self._closeval)
            await self.transmission.write(value=0)
        if int(tripped) != self.interlock.value:
            await self.interlock.write(value=int(tripped))

    @opn.startup
    async def opn(self, instance, async_lib):
        await self.state.write(value=self._openval)
        await self.transmission.write(value=1)

    @opn.putter
    async def opn(self, instance, value):
        if self.tripped():
            return
        await self.state.write(value=self._openval)
        await self.transmission.write(value=1)
