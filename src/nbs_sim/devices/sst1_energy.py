import asyncio
from caproto.server import PVGroup, SubGroup, pvproperty, PvpropertyDouble
from caproto import ChannelType
from .motors import FakeMotor, FakeFMBOMotor
import numpy as np


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
        print(f"Setting energy to {value} in setpoint.putter")
        if self._scanning:
            return

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

            await self.readback.write(current)
            await asyncio.sleep(0.1)  # 10Hz update rate

            if self.stop.value:
                await self.stop.write(0)
                break

        print(f"Done moving, setting to {current}")
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
                async with asyncio.TaskGroup() as group:
                    group.create_task(self.readback.write(current))
                    group.create_task(self.en_mon.write(current))
                    group.create_task(asyncio.sleep(0.1))  # 10Hz update rate
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
    flymove_speed_rb = pvproperty(name="FlyMove-Speed-RB", value=5.0, read_only=True)
    flymove_go = pvproperty(name="FlyMove-Mtr-SP-Go", value=0)
    flymove_start = pvproperty(name="FlyMove-Mtr-Go.PROC", value=0)
    flymove_stop = pvproperty(name="FlyMove-Mtr.STOP", value=0)
    flymove_moving = pvproperty(name="FlyMove-Mtr.MOVN", value=0)
    flymove_done = pvproperty(name="FlyMove-Mtr.DMOV", value=1)
    flymove_rbv = pvproperty(name="FlyMove-Mtr.RBV", value=0, read_only=True)
    flyscan_type = pvproperty(
        name="FlyScan-Type-SP",
        record="mbbo",
        value="Unidirectional",
        enum_strings=["Unidirectional", "Bidirectional"],
        dtype=ChannelType.ENUM,
    )
    flyscan_n_scans = pvproperty(name="EScanNScans-SP", value=1)
    scan_segments_n = pvproperty(name="NScanRegions-SP", value=1)
    scan_segments = pvproperty(
        name="FlySeg-Energy-SP",
        max_length=11,
        value=[500.0, 1000.0],
        dtype=PvpropertyDouble,
    )
    scan_speed_ev = pvproperty(
        name="FlySeg-Velo-SP",
        value=[5.0],
        max_length=10,
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

    def __init__(self, *args, parent=None, **kwargs):
        self._scanning = False
        self._flymove_task = None
        self._mono = parent.mono
        self._epu = parent.undulator
        super().__init__(*args, parent=parent, **kwargs)

    @undulator_dance_enable.putter
    async def undulator_dance_enable(self, instance, value):
        """Handle undulator dance enable."""
        await self.undulator_dance_readback.write(value)
        if value == 1:
            # Simulate enabling by setting bit 2 (value 4) after delay
            await self.undulator_dance_readback.write(1)
            await asyncio.sleep(2.0)
            await self.undulator_dance_readback.write(4)
        else:
            await self.undulator_dance_readback.write(2)

    @flymove_go.putter
    async def flymove_go(self, instance, value):
        """Handle flymove go command."""
        await self.flymove_stop_ev.write(value)
        await self.flymove_start.write(1)

    @flymove_start.putter
    async def flymove_start(self, instance, value):
        """Handle flymove start command."""
        if value == 1 and not self._scanning:
            await self.flymove_moving.write(1)
            await self.flymove_done.write(0)
            target = self.flymove_stop_ev.value
            speed = self.flymove_speed_ev.value

            self._flymove_task = asyncio.create_task(self._run_move(target, speed))

    @flymove_speed_ev.putter
    async def flymove_speed_ev(self, instance, value):
        await self.flymove_speed_rb.write(value)

    @flymove_rbv.scan(period=0.1)
    async def flymove_rbv(self, instance, async_lib):
        """Handle flymove readback."""
        await instance.write(self._mono.readback.value)

    async def _run_move(self, target, speed):
        """Run a fly move to target position."""
        try:
            current = self._mono.readback.value
            current_speed = self._mono.velocity.value
            await self._mono.velocity.write(speed)
            await self._mono.setpoint.write(target)

            await self.flymove_moving.write(0)
            await self.flymove_done.write(1)
            await self._mono.velocity.write(current_speed)

        except asyncio.CancelledError:
            await self.flymove_moving.write(0)
            await self.flymove_done.write(1)
            await self._mono.stop.write(1)
            await self._mono.velocity.write(current_speed)

    @scan_start_go.putter
    async def scan_start_go(self, instance, value):
        """Handle scan start command."""
        if value == 1 and not self._scanning:
            self._scanning = True
            await self.scanning.write(1)
            print(f"Scanning segments: {self.scan_segments.value}")
            print(f"Scanning speed: {self.scan_speed_ev.value}")
            segments = self.scan_segments.value
            speeds = self.scan_speed_ev.value

            self._scan_task = asyncio.create_task(self._run_scan(segments, speeds))

    async def _run_scan(self, segments, speeds):
        """Run the energy scan.

        Performs energy scan based on scan type (unidirectional/bidirectional)
        and number of scans. For unidirectional scans, returns to start at 10x speed.
        """
        print("Running scan task")

        if True:
            num_scans = self.flyscan_n_scans.value
            is_bidirectional = bool(self.flyscan_type.value)
            segments = np.array(segments)
            if np.isscalar(speeds):
                speeds = [speeds]*(len(segments) - 1)
            speeds = np.array(speeds)
            if len(speeds) != len(segments) - 1:
                raise ValueError(f"Number of speeds ({len(speeds)}) must be one less than number of segments ({len(segments)})")
            start = segments[0]
            print(f"Setting energy to {start} in _run_scan")
            print(f"Mono is {self._mono} with setpoint {self._mono.setpoint.value}")
            await self._mono.setpoint.write(start)
            print(f"Setting scanning to 1")
            await self.scanning.write(1)
            self._scanning = True
            for scan in range(num_scans):
                print(f"Scan {scan} of {num_scans}")
                if not self._scanning:
                    await self.scanning.write(0)
                    break
                for n in range(len(segments) - 1):
                    print(f"Segment {n} of {len(segments) - 1}")
                    start = segments[n]
                    stop = segments[n + 1]

                    if start < stop:
                        speed = speeds[n]
                    else:
                        speed = -speeds[n]

                    print(f"Start: {start}, Stop: {stop}, Speed: {speed}")

                    current = start
                    current += speed * 0.1  # Increment based on speed
                    async with asyncio.TaskGroup() as group:
                        group.create_task(self._mono.readback.write(current))
                        group.create_task(self._mono.en_mon.write(current))
                        group.create_task(asyncio.sleep(0.1))
                    upper = max(start, stop)
                    lower = min(start, stop)

                    while self._scanning and current > lower and current < upper:
                        async with asyncio.TaskGroup() as group:
                            group.create_task(self._mono.readback.write(current))
                            group.create_task(self._mono.en_mon.write(current))
                            group.create_task(asyncio.sleep(0.1))
                        current += speed * 0.1  # Increment based on speed

                    if self._scanning:
                        await self._mono.readback.write(stop)
                        await self._mono.en_mon.write(stop)
                    else:
                        await self.scanning.write(0)
                        break
                if is_bidirectional:
                    segments = segments[::-1]
                    speeds = speeds[::-1]
                else:
                    await self._mono.setpoint.write(segments[0])
            self._scanning = False
            await self.scanning.write(0)

        #except asyncio.CancelledError:
        if False:
            print("Scan cancelled")
            self._scanning = False
            await self.scanning.write(0)

    # Add trigger width and count update methods
    @scan_trigger_width.putter
    async def scan_trigger_width(self, instance, value):
        await self.scan_trigger_width_rb.write(value)

    @scan_trigger_n.putter
    async def scan_trigger_n(self, instance, value):
        await self.scan_trigger_n_rb.write(value)
