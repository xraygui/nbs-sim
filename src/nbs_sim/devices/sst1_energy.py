import asyncio
from caproto.server import PVGroup, SubGroup, pvproperty, PvpropertyDouble
from caproto import ChannelType
from .motors import FakeMotor


class SST1TypeBase(PVGroup):
    """Base class for SST1 type selection (gratings, mirrors, etc.)."""

    setpoint = pvproperty(name="_TYPE_SP", dtype=ChannelType.ENUM)
    readback = pvproperty(name="_TYPE_MON", dtype=ChannelType.ENUM, read_only=True)
    actuate = pvproperty(name="_DCPL_CALC.PROC")
    enable = pvproperty(name="_ENA_CMD.PROC")
    kill = pvproperty(name="_KILL_CMD.PROC")
    home = pvproperty(name="_HOME_CMD.PROC")
    clear = pvproperty(name="_ENC_LSS_CLR_CMD.PROC")
    done = pvproperty(name="_AXIS_STS", value=1)

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


class SST1MonoGrating(SST1TypeBase):
    """Grating type selection with specific enum strings."""

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


class SST1MonoMirror(SST1TypeBase):
    """Mirror type selection with specific enum strings."""

    setpoint = pvproperty(
        name="_TYPE_SP",
        record="mbbo",
        value="au_stripe1",
        enum_strings=["au_stripe1", "au_stripe2", "ni_stripe1", "ni_stripe2"],
        dtype=ChannelType.ENUM,
    )
    readback = pvproperty(
        name="_TYPE_MON",
        record="mbbo",
        value="au_stripe1",
        enum_strings=["au_stripe1", "au_stripe2", "ni_stripe1", "ni_stripe2"],
        dtype=ChannelType.ENUM,
        read_only=True,
    )


class SST1Mono(PVGroup):
    """Simulated SST1 Monochromator."""

    grating = SubGroup(FakeMotor, prefix="GrtP}Mtr", value=0)
    mirror2 = SubGroup(FakeMotor, prefix="MirP}Mtr", value=0)
    gratingx = SubGroup(SST1MonoGrating, prefix="GrtX}Mtr")
    mirror2x = SubGroup(SST1MonoMirror, prefix="MirX}Mtr")
    cff = pvproperty(name=":CFF_SP", value=1.55, dtype=PvpropertyDouble)
    vls = pvproperty(name=":VLS_B2.A", value=0.0)

    setpoint = pvproperty(name=":ENERGY_SP", value=500.0)
    readback = pvproperty(name=":ENERGY_MON", value=500.0, read_only=True)
    velocity = pvproperty(name=":ENERGY_VELO", value=5.0)
    done = pvproperty(name=":ERDY_STS", value=1)
    stop = pvproperty(name=":ENERGY_ST_CMD", value=0)

    # Scan parameters
    scan_start = pvproperty(name=":EVSTART_SP", value=500.0)
    scan_stop = pvproperty(name=":EVSTOP_SP", value=1000.0)
    scan_speed = pvproperty(name=":EVVELO_SP", value=10.0)
    scan_start_cmd = pvproperty(name=":START_CMD.PROC", value=0)
    scan_stop_cmd = pvproperty(name=":ENERGY_ST_CMD.PROC", value=0)

    def __init__(self, prefix, delay=0.1, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self._delay = delay
        self._scanning = False
        self._scan_task = None

    @setpoint.putter
    async def setpoint(self, instance, value):
        """Handle normal setpoint moves."""
        if self._scanning:
            return

        await self.done.write(0)
        await instance.write(value, verify_value=False)

        current = self.readback.value
        target = value
        speed = self.velocity.value

        while abs(current - target) > 0.01:  # Small threshold for "close enough"
            direction = 1 if target > current else -1
            step = direction * speed * 0.1  # 0.1s worth of movement

            # Don't overshoot
            if abs(step) > abs(target - current):
                current = target
            else:
                current += step

            await self.readback.write(current)
            await asyncio.sleep(0.1)  # 10Hz update rate

            if self.stop.value:
                break

        await self.readback.write(current)
        await self.done.write(1)

    @scan_start_cmd.putter
    async def scan_start_cmd(self, instance, value):
        """Handle scan start command."""
        if value == 1 and not self._scanning:
            self._scanning = True
            await self.done.write(0)
            self._scan_task = asyncio.create_task(self._run_scan())

    @scan_stop_cmd.putter
    async def scan_stop_cmd(self, instance, value):
        """Handle scan stop command."""
        if value == 1 and self._scanning:
            self._scanning = False
            if self._scan_task is not None:
                self._scan_task.cancel()
                self._scan_task = None
            await self.done.write(1)

    async def _run_scan(self):
        """Run the energy scan."""
        try:
            start = self.scan_start.value
            stop = self.scan_stop.value
            speed = self.scan_speed.value
            current = start

            while self._scanning and current <= stop:
                await self.readback.write(current)
                await asyncio.sleep(0.1)  # 10Hz update rate
                current += speed * 0.1  # Increment based on speed

            self._scanning = False
            await self.done.write(1)

        except asyncio.CancelledError:
            self._scanning = False
            await self.done.write(1)
