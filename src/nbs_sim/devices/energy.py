import asyncio
import functools
from caproto.server import (
    PVGroup,
    SubGroup,
    pvproperty,
    PvpropertyDouble,
)
from .sst1_energy import SST1Mono, SST1FlyControl
from .hax_dcm import DCM
from .motors import FakeUndulatorMotor, FakePositioner
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


class SSTEPU(PVGroup):
    """Simulated SST EPU device."""

    gap = SubGroup(
        FakeUndulatorMotor,
        prefix="Gap}-Mtr",
        velocity=800.0,
        value=14000.0,
        acceleration=0.25,
        settling_time=0.25,
    )
    phase = SubGroup(
        FakeUndulatorMotor,
        prefix="Phase}-Mtr",
        velocity=5000.0,
        value=0.0,
        acceleration=0,
    )
    mode = SubGroup(
        FakePositioner, prefix="Phase}Phs:Mode", value=2
    )  # 2 is linear horizontal


class SST1Energy(PVGroup):
    """Simulated SST1 Energy System."""

    mono = SubGroup(SST1Mono, prefix="XF:07ID1-OP{Mono:PGM1-Ax:")
    epu60 = SubGroup(SSTEPU, prefix="SR:C07-ID:G1A{SST1:1-Ax:")
    flyer = SubGroup(SST1FlyControl, prefix="SR:C07-ID:G1A{SST1:1}")

    @property
    def value(self):
        return self.mono.readback.value


class HAXEnergy(PVGroup):
    """Simulated HAX Energy System."""

    u42 = SubGroup(SSTEPU, prefix="SR:C07-ID:G1A{SST2:1-Ax:")
    mono = SubGroup(DCM, prefix="XF:07ID6-OP{Mono:DCM1-Ax:")
    harmonic = pvproperty(name="XF:07ID2-HAXMonitor:U42harmonic", value=3, dtype=int)

    @property
    def value(self):
        return self.mono.readback.value
