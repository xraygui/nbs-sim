import asyncio
import functools
from caproto.server import (
    PVGroup,
    SubGroup,
    pvproperty,
    PvpropertyDouble,
)
from .sst1_energy import SST1Mono, SST1FlyControl
from .hax_dcm import DCM, DCM_energy
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
    tu_enable = pvproperty(name="TU}Sw:AmpEn-Sts", value=1)
    td_enable = pvproperty(name="TD}Sw:AmpEn-Sts", value=1)

class SST1Energy(PVGroup):
    """Simulated SST1 Energy System."""

    mono = SubGroup(SST1Mono, prefix="XF:07ID1-OP{Mono:PGM1-Ax:")
    undulator = SubGroup(SSTEPU, prefix="SR:C07-ID:G1A{SST1:1-Ax:")
    flyer = SubGroup(SST1FlyControl, prefix="SR:C07-ID:G1A{SST1:1}")

    @property
    def value(self):
        return self.mono.readback.value


class HAXEnergy(PVGroup):
    """Simulated HAX Energy System."""

    undulator = SubGroup(SSTEPU, prefix="SR:C07-ID:G1A{SST2:1-Ax:")
    mono = SubGroup(DCM, prefix="XF:07ID6-OP{Mono:DCM1-Ax:")
    harmonic = pvproperty(name="XF:07ID2-HAXMonitor:U42harmonic", value=3, dtype=int)

    @property
    def value(self):
        return self.mono.readback.value

class HAXEnergyFlyer(PVGroup):
    undulator = SubGroup(SSTEPU, prefix="SR:C07-ID:G1A{SST2:1-Ax:")
    mono = SubGroup(DCM_energy, prefix="XF:07ID6-OP{Mono:DCM1-Ax:")
    harmonic = pvproperty(name="XF:07ID2-HAXMonitor:U42harmonic", value=3, dtype=int)
    flyer = SubGroup(SST1FlyControl, prefix="SR:C07-ID:G1A{SST2:1}")
    mode = pvproperty(name = "XF:07ID6-OP{MC:08}DCM_MODE", dtype=str)
    mode_rbv = pvproperty(name = "XF:07ID6-OP{MC:08}DCM_MODE_RBV", dtype=str)
    offset_gap_rb = pvproperty(name="SR:C07-ID:G1A{SST2:1}EScanIDEnergyOffset-RB")
    offset_gap_sp = pvproperty(name="SR:C07-ID:G1A{SST2:1}EScanIDEnergyOffset-SP")
    flyharmonic_rb = pvproperty(name="SR:C07-ID:G1A{SST2:1}FlyHarmonic-RB", value=1)
    flyharmonic_sp = pvproperty(name="SR:C07-ID:G1A{SST2:1}FlyHarmonic-SP", value=1)
    flyenergy = pvproperty(name="SR:C07-ID:G1A{SST2:1}FlyEnergyDCM-RB", value=0)

    @flyenergy.scan(period=0.1)
    async def flyenergy(self, instance, async_lib):
        await instance.write(self.mono.readback.value)
        
    @property
    def value(self):
        return self.mono.readback.value

    @mode.putter
    async def mode(self, instance, value):
        await self.mode_rbv.write(value)

    @offset_gap_sp.putter
    async def offset_gap_sp(self, instance, value):
        await self.offset_gap_rb.write(value)

    @flyharmonic_sp.putter
    async def flyharmonic_sp(self, instance, value):
        await self.flyharmonic_rb.write(value)