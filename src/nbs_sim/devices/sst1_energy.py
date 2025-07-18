import asyncio
from caproto.server import PVGroup, SubGroup, pvproperty, PvpropertyDouble
from caproto import ChannelType
from .motors import FakeMotor, FakeFMBOMotor


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

    grating = SubGroup(FakeFMBOMotor, prefix="GrtP}Mtr", value=0, acceleration=0.1)
    mirror2 = SubGroup(FakeFMBOMotor, prefix="MirP}Mtr", value=0, acceleration=0.1)
    gratingx = SubGroup(SST1MonoGrating, prefix="GrtX}Mtr")
    mirror2x = SubGroup(SST1MonoMirror, prefix="MirX}Mtr")
    cff = pvproperty(name=":CFF_SP", value=1.55, dtype=PvpropertyDouble)
    vls = pvproperty(name=":VLS_B2.A", value=0.0)

    setpoint = pvproperty(name=":ENERGY_SP", value=500.0)
    readback = pvproperty(name=":ENERGY_MON", value=500.0, read_only=True)
    en_mon = pvproperty(name=":READBACK2.A", value=500.0, read_only=True)

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
        self._flymove_task = None

    @setpoint.putter
    async def setpoint(self, instance, value):
        """Handle normal setpoint moves."""
        if self._scanning:
            return

        await self.done.write(0)
        await self.stop.write(0)
        await instance.write(value, verify_value=False)

        current = self.readback.value
        target = value
        speed = self.velocity.value
        # print(f"Setting energy to {value} from {current} at {speed} mm/s")
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

            await self.readback.write(current)
            await asyncio.sleep(0.1)  # 10Hz update rate

            if self.stop.value:
                await self.stop.write(0)
                break

        # print(f"Done moving, setting to {current}")
        await self.readback.write(current)
        await self.en_mon.write(current)
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
                await self.en_mon.write(current)
                await asyncio.sleep(0.1)  # 10Hz update rate
                current += speed * 0.1  # Increment based on speed

            self._scanning = False
            await self.done.write(1)

        except asyncio.CancelledError:
            self._scanning = False
            await self.done.write(1)


class SST1FlyControl(PVGroup):
    # Add FlyControl PVs
    undulator_dance_enable = pvproperty(
        name="MACROControl-SP",
        value=0,
        dtype=PvpropertyDouble,
    )
    undulator_dance_readback = pvproperty(
        name="MACROControl-RB",
        value=0,
        dtype=PvpropertyDouble,
        read_only=True,
    )

    flymove_stop_ev = pvproperty(
        name="FlyMove-Mtr-SP",
        value=500.0,
        dtype=PvpropertyDouble,
    )
    flymove_speed_ev = pvproperty(
        name="FlyMove-Speed-SP",
        value=5.0,
        dtype=PvpropertyDouble,
    )
    flymove_start = pvproperty(name="FlyMove-Mtr-Go.PROC", value=0)
    flymove_stop = pvproperty(name="FlyMove-Mtr.STOP", value=0)
    flymove_moving = pvproperty(name="FlyMove-Mtr.MOVN", value=0)
    flyscan_type = pvproperty(
        name="FlyScan-Type-SP",
        record="mbbo",
        value="Unidirectional",
        enum_strings=["Unidirectional", "Bidirectional"],
        dtype=ChannelType.ENUM,
    )
    flyscan_n_scans = pvproperty(name="EScanNScans-SP", value=1)
    scan_start_ev = pvproperty(
        name="EScanFirst-SP",
        value=500.0,
        dtype=PvpropertyDouble,
    )
    scan_stop_ev = pvproperty(
        name="EScanLast-SP",
        value=1000.0,
        dtype=PvpropertyDouble,
    )
    scan_speed_ev = pvproperty(
        name="EScan-Speed-SP",
        value=5.0,
        dtype=PvpropertyDouble,
    )
    scan_trigger_width = pvproperty(
        name="EScanTriggerWidth-SP",
        value=0.1,
        dtype=PvpropertyDouble,
    )
    scan_trigger_width_rb = pvproperty(
        name="EScanTriggerWidth-RB",
        value=0.1,
        dtype=PvpropertyDouble,
        read_only=True,
    )
    scan_trigger_n = pvproperty(
        name="EScanNTriggers-SP",
        value=10,
        dtype=PvpropertyDouble,
    )
    scan_trigger_n_rb = pvproperty(
        name="EScanNTriggers-RB",
        value=10,
        dtype=PvpropertyDouble,
        read_only=True,
    )
    scan_start_go = pvproperty(name="FlyScan-Mtr-Go.PROC", value=0)
    scanning = pvproperty(name="FlyScan-Mtr.MOVN", value=0)

    def __init__(self, *args, **kwargs):
        self._scanning = False
        self._flymove_task = None
        super().__init__(*args, **kwargs)

    @undulator_dance_enable.putter
    async def undulator_dance_enable(self, instance, value):
        """Handle undulator dance enable."""
        await self.undulator_dance_readback.write(value)
        if value == 1:
            # Simulate enabling by setting bit 2 (value 4) after delay
            await asyncio.sleep(2.0)
            await self.undulator_dance_readback.write(4)

    @flymove_start.putter
    async def flymove_start(self, instance, value):
        """Handle flymove start command."""
        if value == 1 and not self._scanning:
            await self.flymove_moving.write(1)
            target = self.flymove_stop_ev.value
            speed = self.flymove_speed_ev.value

            self._flymove_task = asyncio.create_task(self._run_move(target, speed))

    async def _run_move(self, target, speed):
        """Run a fly move to target position."""
        try:
            current = self.readback.value

            while abs(current - target) > 0.01:
                direction = 1 if target > current else -1
                step = direction * speed * 0.1

                if abs(step) > abs(target - current):
                    current = target
                else:
                    current += step

                await self.readback.write(current)
                await asyncio.sleep(0.1)

                if self.flymove_stop.value:
                    break

            await self.flymove_moving.write(0)

        except asyncio.CancelledError:
            await self.flymove_moving.write(0)

    @scan_start_go.putter
    async def scan_start_go(self, instance, value):
        """Handle scan start command."""
        if value == 1 and not self._scanning:
            self._scanning = True
            await self.scanning.write(1)

            start = self.scan_start_ev.value
            stop = self.scan_stop_ev.value
            speed = self.scan_speed_ev.value

            self._scan_task = asyncio.create_task(self._run_scan(start, stop, speed))

    async def _run_scan(self, start, stop, speed):
        """Run the energy scan.

        Performs energy scan based on scan type (unidirectional/bidirectional)
        and number of scans. For unidirectional scans, returns to start at 10x speed.
        """
        try:
            speed = abs(speed)
            num_scans = self.flyscan_n_scans.value
            is_bidirectional = bool(self.flyscan_type.value)

            for scan in range(num_scans):

                # Forward scan
                current = start
                while self._scanning and current <= stop:
                    await self.readback.write(current)
                    await asyncio.sleep(0.1)
                    current += speed * 0.1

                if not self._scanning:
                    break

                # Reverse scan if bidirectional
                if is_bidirectional:
                    current = stop
                    while self._scanning and current >= start:
                        await self.readback.write(current)
                        await asyncio.sleep(0.1)
                        current -= speed * 0.1
                else:
                    current = stop
                    fast_speed = speed * 10
                    while self._scanning and current >= start:
                        await self.readback.write(current)
                        await asyncio.sleep(0.1)
                        current -= fast_speed * 0.1
                # Return to start at 10x speed for next unidirectional scan

                if not self._scanning:
                    break

            self._scanning = False
            await self.scanning.write(0)

        except asyncio.CancelledError:
            self._scanning = False
            await self.scanning.write(0)

    # Add trigger width and count update methods
    @scan_trigger_width.putter
    async def scan_trigger_width(self, instance, value):
        await self.scan_trigger_width_rb.write(value)

    @scan_trigger_n.putter
    async def scan_trigger_n(self, instance, value):
        await self.scan_trigger_n_rb.write(value)
