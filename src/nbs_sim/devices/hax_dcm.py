import asyncio
from caproto.server import PVGroup, SubGroup, pvproperty
from nbs_sim.devices.motors import FakeMotor
from caproto import ChannelType
from math import sin, pi


class DCM(PVGroup):
    """Simulated Double Crystal Monochromator Hardware."""

    # Configuration PVs
    d = pvproperty(name=":XTAL_CONST_MON", value=3.1356, read_only=True)
    hc = pvproperty(name=":HC_SP", value=1, read_only=True)
    beam_offset = pvproperty(name=":BEAM_OFF_SP", value=10.829, read_only=True)
    crystal = pvproperty(
        name=":XTAL_SEL",
        dtype=ChannelType.ENUM,
        value="Si(111)",
        enum_strings=["Si(111)", "Si(220)", "Si(333)", "Si(444)"],
    )
    crystal_move = pvproperty(name=":XTAL_CMD.PROC", value=0)
    crystal_status = pvproperty(name=":XTAL_STS", value=1)
    readback = pvproperty(name=":ENERGY_MON", value=1820.0, read_only=True)
    stop_signal = pvproperty(name=":ENERGY_ST_CMD", value=0)

    # Motors
    bragg = SubGroup(FakeMotor, prefix="Bragg}Mtr", user_limits=(1, 10), value=5)
    x2perp = SubGroup(FakeMotor, prefix="Per2}Mtr")
    x2para = SubGroup(FakeMotor, prefix="Par2}Mtr")
    x2roll = SubGroup(FakeMotor, prefix="R2}Mtr")
    x2pitch = SubGroup(FakeMotor, prefix="P2}Mtr")
    x2finepitch = SubGroup(FakeMotor, prefix="PF2}Mtr")
    x2fineroll = SubGroup(FakeMotor, prefix="RF2}Mtr")

    def __init__(self, prefix, *, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self._moving = False

    @crystal_move.putter
    async def crystal_move(self, instance, value):
        """Handle crystal movement command."""
        if value == 1 and not self._moving:
            self._moving = True
            await self.crystal_status.write(0)
            await instance.write(1)
            await asyncio.sleep(5.0)
            await instance.write(0)
            await self.crystal_status.write(1)
            self._moving = False

    async def _calc_energy(self, bragg_deg):
        """Calculate energy from bragg angle, handling edge cases."""
        MAX_ENERGY = 10000.0  # 10 keV maximum
        if abs(bragg_deg) < 0.1:  # Avoid angles too close to zero
            return MAX_ENERGY
        try:
            energy = (
                1000 * self.hc.value / (2 * self.d.value * sin(bragg_deg * pi / 180))
            )
            return min(energy, MAX_ENERGY)
        except (ZeroDivisionError, ValueError):
            return MAX_ENERGY

    @readback.scan(period=0.1)
    async def readback(self, instance, async_lib):
        """Calculate energy from bragg angle."""
        bragg_deg = self.bragg.motor.value
        energy = await self._calc_energy(bragg_deg)
        await instance.write(energy)
