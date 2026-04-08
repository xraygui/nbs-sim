import asyncio
from caproto.server import PVGroup, SubGroup, pvproperty
from nbs_sim.devices.motors import FakeFMBOMotor as FakeMotor
from caproto import ChannelType
from math import asin, pi, sin

class DCM_energy(PVGroup):
    """ Simulated DCM without bragg motor, just energy setpoint, readback, velocity """
    setpoint = pvproperty(name=":ENERGY_SP", value=1820.0)
    readback = pvproperty(name=":ENERGY_MON", value=1820.0, read_only=True)
    en_mon = pvproperty(name=":READBACK2.A", value=1820.0, read_only=True) # Not sure if this actually exists for DCM but can always ignore it
    done = pvproperty(name=":ERDY_STS", value=1)
    stop = pvproperty(name=":ENERGY_ST_CMD.PROC", value=0)
    enable_signal = pvproperty(name=":ENA_CMD.PROC", value=0)

    velocity = pvproperty(name=":ENERGY_VELO", value=5.0)

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

    @setpoint.putter
    async def setpoint(self, instance, value):
        """Handle normal setpoint moves."""
        print(f"Setting energy to {value} in setpoint.putter")

        await self.done.write(0)
        await self.stop.write(0)
        await instance.write(value, verify_value=False)

        current = self.readback.value
        target = value
        speed = self.velocity.value
        print(f"Setting energy to {value} from {current} at {speed} mm/s")
        while abs(current - target) > 0.01:  # Small threshold for "close enough"
            direction = 1 if target > current else -1
            step = direction * speed * 0.1  # 0.1s worth of movement

            # Don't overshoot
            if abs(step) > abs(target - current):
                # print(f"Overshooting, setting to {target}")
                current = target
            else:
                # print(f"Moving {step} to {current + step}")
                current += step

            async with asyncio.TaskGroup() as group:
                group.create_task(self.readback.write(current))
                group.create_task(self.en_mon.write(current))
                group.create_task(asyncio.sleep(0.1))

            if self.stop.value:
                await self.stop.write(0)
                break

        print(f"Done moving, setting to {current}")
        await self.readback.write(current)
        await self.en_mon.write(current)
        await self.done.write(1)

# class DCM(PVGroup):
#     """Simulated Double Crystal Monochromator Hardware."""

#     # Configuration PVs
#     d = pvproperty(name=":XTAL_CONST_MON", value=3.1356, read_only=True)
#     hc = pvproperty(name=":HC_SP", value=1, read_only=True)
#     beam_offset = pvproperty(name=":BEAM_OFF_SP", value=10.829, read_only=True)
#     crystal = pvproperty(
#         name=":XTAL_SEL",
#         dtype=ChannelType.ENUM,
#         value="Si(111)",
#         enum_strings=["Si(111)", "Si(220)", "Si(333)", "Si(444)"],
#     )
#     crystal_move = pvproperty(name=":XTAL_CMD.PROC", value=0)
#     crystal_status = pvproperty(name=":XTAL_STS", value=1)
#     readback = pvproperty(name=":ENERGY_MON", value=1820.0, read_only=True)
#     setpoint = pvproperty(name=":ENERGY_SP", value=1820.0)

#     stop_signal = pvproperty(name=":ENERGY_ST_CMD.PROC", value=0)
#     enable_signal = pvproperty(name=":ENA_CMD.PROC", value=0)

#     # Motors
#     bragg = SubGroup(FakeMotor, prefix="Bragg}Mtr", user_limits=(1, 10), value=5)
#     x2perp = SubGroup(FakeMotor, prefix="Per2}Mtr")
#     x2para = SubGroup(FakeMotor, prefix="Par2}Mtr")
#     x2roll = SubGroup(FakeMotor, prefix="R2}Mtr")
#     x2pitch = SubGroup(FakeMotor, prefix="P2}Mtr")
#     x2finepitch = SubGroup(FakeMotor, prefix="PF2}Mtr")
#     x2fineroll = SubGroup(FakeMotor, prefix="RF2}Mtr")

#     def __init__(self, prefix, *, parent=None, **kwargs):
#         super().__init__(prefix, parent=parent)
#         self._moving = False

#     @crystal_move.putter
#     async def crystal_move(self, instance, value):
#         """Handle crystal movement command."""
#         if value == 1 and not self._moving:
#             self._moving = True
#             await self.crystal_status.write(0)
#             await instance.write(1)
#             await asyncio.sleep(5.0)
#             await instance.write(0)
#             await self.crystal_status.write(1)
#             self._moving = False

#     async def _calc_energy(self, bragg_deg):
#         """Calculate energy from bragg angle, handling edge cases."""
#         MAX_ENERGY = 10000.0  # 10 keV maximum
#         if abs(bragg_deg) < 0.1:  # Avoid angles too close to zero
#             return MAX_ENERGY
#         try:
#             energy = (
#                 1000 * self.hc.value / (2 * self.d.value * sin(bragg_deg * pi / 180))
#             )
#             return min(energy, MAX_ENERGY)
#         except (ZeroDivisionError, ValueError):
#             return MAX_ENERGY

#     def _calc_bragg(self, energy_ev):
#         """
#         Calculate bragg angle in degrees from energy.

#         Inverts the formula used by _calc_energy:
#         E = 1000 * hc / (2 * d * sin(theta))
#         theta = arcsin(1000 * hc / (E * 2 * d)) * 180/pi

#         Parameters
#         ----------
#         energy_ev : float
#             Photon energy in eV.

#         Returns
#         -------
#         float
#             Bragg angle in degrees.

#         Raises
#         ------
#         ValueError
#             If energy is invalid (<= 0) or would produce a mathematically
#             invalid arcsin argument.
#         """
#         if energy_ev <= 0:
#             raise ValueError(
#                 f"Energy must be positive, got {energy_ev}"
#             )
#         arg = 1000 * self.hc.value / (energy_ev * 2 * self.d.value)
#         if abs(arg) > 1:
#             raise ValueError(
#                 f"Energy {energy_ev} eV produces invalid bragg angle "
#                 f"(sin arg={arg})"
#             )
#         bragg_rad = asin(arg)
#         return bragg_rad * 180 / pi

#     @readback.scan(period=0.1)
#     async def readback(self, instance, async_lib):
#         """Calculate energy from bragg angle."""
#         bragg_deg = self.bragg.motor.value
#         energy = await self._calc_energy(bragg_deg)
#         await instance.write(energy)

#     @setpoint.putter
#     async def setpoint(self, instance, value):
#         """Update energy setpoint and drive bragg motor to required angle."""
#         await instance.write(value)
#         bragg_deg = self._calc_bragg(value)
#         await self.bragg.motor.write(bragg_deg)
