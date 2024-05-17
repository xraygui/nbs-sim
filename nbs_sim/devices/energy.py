import asyncio
import functools
from caproto.server import (
    PVGroup,
    SubGroup,
    ioc_arg_parser,
    pvproperty,
    run,
    PvpropertyDouble,
)
from caproto.ioc_examples.fake_motor_record import FakeMotor
from caproto import ChannelType, SkipWrite
import contextvars

internal_process = contextvars.ContextVar("internal_process", default=False)


def no_reentry(func):
    @functools.wraps(func)
    async def inner(*args, **kwargs):
        if internal_process.get():
            return
        try:
            internal_process.set(True)
            return await func(*args, **kwargs)
        finally:
            internal_process.set(False)

    return inner


class SST1MonoGrating(PVGroup):
    setpoint = pvproperty(
        name="_TYPE_SP",
        record="mbbo",
        value="1200l/mm",
        enum_strings=[
            "ZERO",
            "ONE",
            "250l/mm",
            "THREE",
            "FOUR",
            "FIVE",
            "SIX",
            "SEVEN",
            "EIGHT",
            "1200l/mm",
        ],
        dtype=ChannelType.ENUM,
    )
    readback = pvproperty(
        name="_TYPE_MON",
        record="mbbo",
        value="1200l/mm",
        enum_strings=["1200l/mm", "250l/mm"],
        dtype=ChannelType.ENUM,
        read_only=True,
    )
    actuate = pvproperty(name="_DCPL_CALC.PROC")
    enable = pvproperty(name="_ENA_CMD.PROC")
    kill = pvproperty(name="_KILL_CMD.PROC")
    home = pvproperty(name="_HOME_CMD.PROC")
    clear = pvproperty(name="_ENC_LSS_CLR_CMD.PROC")
    done = pvproperty(name="_AXIS_STS")

    def __init__(self, prefix, delay=0.5, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self._delay = delay

    @actuate.putter
    async def actuate(self, instance, value):
        await self.done.write(0)
        await asyncio.sleep(self._delay)
        sp = self.setpoint.value
        await self.readback.write(value=sp)
        await self.done.write(1)


class SST1MonoMotor(PVGroup):
    setpoint = pvproperty(name=":ENERGY_SP", value=500.0)
    readback = pvproperty(name=":ENERGY_MON", value=500.0, read_only=True)
    velocity = pvproperty(name=":ENERGY_VELO", value=200.0)
    done = pvproperty(name=":ERDY_STS")

    def __init__(self, prefix, delay=0.1, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self._delay = delay

    @setpoint.putter
    async def setpoint(self, instance, value):
        await self.done.write(0)
        await asyncio.sleep(self._delay)
        await instance.write(value, verify_value=False)
        await self.readback.write(value)
        await self.done.write(1)
        return SkipWrite


class SST1Mono(PVGroup):
    mono = SubGroup(SST1MonoMotor, prefix="")
    gratingx = SubGroup(SST1MonoGrating, prefix="GrtX}}Mtr")
    cff = pvproperty(name=":CFF_SP", value=1.55, dtype=PvpropertyDouble)

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)


class SST1Energy(PVGroup):
    mono = SubGroup(SST1Mono, prefix="MonoMtr")
    gap = SubGroup(FakeMotor, prefix="GapMtr", velocity=5000.0, precision=3)
    phase = SubGroup(FakeMotor, prefix="PhaseMtr", velocity=5000.0, precision=3)
    mode = SubGroup(FakeMotor, prefix="ModeMtr", velocity=100.0, precision=3)

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)

    @property
    def value(self):
        return self.mono.mono.readback.value
