"""Simulated signals for beamline devices."""

from caproto.server import (
    PVGroup,
    pvproperty,
)
from caproto import ChannelType
import numpy as np
import time

class Signal(PVGroup):
    value = pvproperty(value=0.0, dtype=float, doc="Signal value", name="")

    def __init__(self, prefix, *, value=0.0, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self.initial_value = value

    @value.startup
    async def value(self, instance, async_lib):
        await instance.write(value=self.initial_value)

class ConstantSignal(PVGroup):
    """Simulated signal that outputs a constant value with a period of 0.1 seconds

    Parameters
    ----------
    value : float
        The constant value to output
    """

    value = pvproperty(value=0.0, dtype=float, doc="Constant value", name="")

    def __init__(self, prefix, *, value=0.0, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self._value = value

    @value.scan(period=0.1)
    async def value(self, instance, async_lib):
        await instance.write(value=self._value)

    @value.putter
    async def value(self, instance, value):
        self._value = value


class SineSignal(PVGroup):
    """Simulated signal that outputs a sine wave.

    Parameters
    ----------
    period : float
        Period of oscillation in seconds
    amplitude : float
        Peak amplitude of oscillation
    offset : float
        DC offset of the signal
    phase : float
        Phase offset in radians
    """

    value = pvproperty(value=0.0, dtype=float, doc="Sine wave value", name="")

    def __init__(
        self,
        prefix,
        *,
        period=1.0,
        amplitude=1.0,
        offset=0.0,
        phase=0.0,
        parent=None,
        **kwargs
    ):
        super().__init__(prefix, parent=parent)
        self.period = period
        self.amplitude = amplitude
        self.offset = offset
        self.phase = phase
        self._t0 = time.time()

    @value.scan(period=0.1)
    async def value(self, instance, async_lib):
        t = time.time() - self._t0
        value = (
            self.amplitude * np.sin(2 * np.pi * t / self.period + self.phase)
            + self.offset
        )
        await instance.write(value=value)


class NoiseSignal(PVGroup):
    """Simulated signal that outputs Gaussian noise around a mean value.

    Parameters
    ----------
    mean : float
        Mean value of the noise
    std : float
        Standard deviation of the noise
    """

    value = pvproperty(value=0.0, dtype=float, doc="Noisy value", name="")

    def __init__(self, prefix, *, mean=0.0, std=1.0, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self.mean = mean
        self.std = std

    @value.scan(period=0.1)
    async def value(self, instance, async_lib):
        value = self.mean + self.std * np.random.randn()
        await instance.write(value=value)


class RingCurrent(PVGroup):
    current = pvproperty(
        value=0, dtype=float, read_only=True, doc="Ring Current", name=""
    )

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)

    @current.scan(period=0.1)
    async def current(self, instance, async_lib):
        value = self.parent.current_func()
        await instance.write(value=value)


class ModeControl(PVGroup):
    """Simulated beamline mode control.

    Provides an enum PV for switching between Soft and Tender modes.
    """

    mode = pvproperty(
        name="",
        record="mbbo",
        value="Tender",
        enum_strings=["Soft", "Tender", "None"],
        dtype=ChannelType.ENUM,
        doc="Beamline Mode",
    )

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)


class EndstationControl(PVGroup):
    """Simulated beamline mode control.

    Provides an enum PV for switching between Soft and Tender modes.
    """

    mode = pvproperty(
        name="",
        record="mbbo",
        value="NEXAFS",
        enum_strings=["NEXAFS", "HAXPES", "RSOXS", "VPEEM"],
        dtype=ChannelType.ENUM,
        doc="Endstation Mode",
    )

    def __init__(self, prefix, parent=None, value="NEXAFS", **kwargs):
        super().__init__(prefix, parent=parent)
        self.initial_value = value

    @mode.startup
    async def mode(self, instance, async_lib):
        await instance.write(self.initial_value)
