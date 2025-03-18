from caproto.server import PVGroup, pvproperty
from caproto.ioc_examples.fake_motor_record import motor_record_simulator
import asyncio
import numpy as np
from caproto import ChannelType


class FakeMotor(PVGroup):
    """Standard EPICS Motor Record simulation."""

    motor = pvproperty(value=0.0, name="", record="motor", precision=3)

    def __init__(
        self,
        prefix,
        velocity=1.0,
        precision=3,
        acceleration=1.0,
        resolution=1e-6,
        user_limits=(0.0, 100.0),
        tick_rate_hz=10.0,
        value=0,
        parent=None,
        **kwargs,
    ):
        super().__init__(prefix, parent=parent)
        self._have_new_position = False
        self.tick_rate_hz = tick_rate_hz
        self.initial_value = value
        self.defaults = {
            "velocity": velocity,
            "precision": precision,
            "acceleration": acceleration,
            "resolution": resolution,
            "user_limits": user_limits,
        }

    @motor.startup
    async def motor(self, instance, async_lib):
        # Start the simulator:
        await instance.write(self.initial_value)
        await motor_record_simulator(
            self.motor,
            async_lib,
            self.defaults,
            tick_rate_hz=self.tick_rate_hz,
        )


class FakeUndulatorMotor(FakeMotor):
    """Simulated Undulator Motor with SP/RB interface and standard motor fields."""

    user_setpoint = pvproperty(name="-SP", value=0.0)

    @user_setpoint.startup
    async def user_setpoint(self, instance, async_lib):
        await instance.write(self.initial_value)

    @user_setpoint.putter
    async def user_setpoint(self, instance, value):
        await instance.write(value, verify_value=False)
        await self.motor.write(value)


class FakePositioner(PVGroup):
    """
    Simple positioner with SP/RB interface, limits, and simulated motion.

    Parameters
    ----------
    value : float, optional
        Initial position value
    velocity : float, optional
        Speed of simulated motion in units/s
    low_limit : float, optional
        Lower limit for motion
    high_limit : float, optional
        Upper limit for motion
    """

    setpoint = pvproperty(name="-SP", value=0)
    readback = pvproperty(name="-RB", value=0, read_only=True)

    def __init__(
        self,
        prefix,
        value=0,
        velocity=1.0,
        low_limit=-np.inf,
        high_limit=np.inf,
        parent=None,
        **kwargs,
    ):
        super().__init__(prefix, parent=parent)
        self.initial_value = value
        self.velocity = velocity
        self.low_limit = low_limit
        self.high_limit = high_limit
        self._move_task = None

    @setpoint.startup
    async def setpoint(self, instance, async_lib):
        await instance.write(self.initial_value)
        await self.readback.write(self.initial_value)

    @setpoint.putter
    async def setpoint(self, instance, value):
        """Handle setpoint changes by simulating motion."""
        # Check limits
        if not (self.low_limit <= value <= self.high_limit):
            raise ValueError(
                f"Value {value} outside limits [{self.low_limit}, "
                f"{self.high_limit}]"
            )

        # Cancel any existing motion
        if self._move_task is not None and not self._move_task.done():
            self._move_task.cancel()
            await self.moving.write(0)
            try:
                await self._move_task
            except asyncio.CancelledError:
                pass

        # Start new motion
        self._move_task = asyncio.create_task(
            self._move_to(value, velocity=self.velocity)
        )
        return value

    async def _move_to(self, target, velocity=1.0):
        """Simulate motion to target position."""
        current = self.readback.value
        distance = abs(target - current)
        if distance > 0 and velocity > 0:
            # Calculate time needed and step size
            time_needed = distance / velocity
            steps = int(time_needed * 10)  # 10 updates per second
            if steps > 0:
                step_size = (target - current) / steps
                for i in range(steps):
                    if self._move_task.cancelled():
                        break
                    new_pos = current + step_size * (i + 1)
                    await self.readback.write(new_pos)
                    await asyncio.sleep(time_needed / steps)

        if not self._move_task.cancelled():
            await self.readback.write(target)


class DelayedFakePositioner(FakePositioner):
    """
    A positioner that delays motion until explicitly commanded.
    """

    def __init__(self, prefix, *args, **kwargs):
        super().__init__(prefix, *args, **kwargs)
        self._pending_setpoint = self.initial_value

    @FakePositioner.setpoint.putter
    async def setpoint(self, instance, value):
        """Store the setpoint without starting motion."""
        # Check limits
        if not (self.low_limit <= value <= self.high_limit):
            raise ValueError(
                f"Value {value} outside limits [{self.low_limit}, "
                f"{self.high_limit}]"
            )
        self._pending_setpoint = value
        return value

    async def start_motion(self):
        """Start motion to the pending setpoint."""
        if self._move_task is not None and not self._move_task.done():
            self._move_task.cancel()
            await self.moving.write(0)
            try:
                await self._move_task
            except asyncio.CancelledError:
                pass

        self._move_task = asyncio.create_task(
            self._move_to(self._pending_setpoint, velocity=self.velocity)
        )
        return self._move_task


class FakeFMBOMotor(FakeMotor):
    """
    Simulated FMBO Motor with additional status signals.

    Parameters
    ----------
    prefix : str
        The PV prefix for this motor
    velocity : float, optional
        Speed of simulated motion in units/s
    precision : int, optional
        Number of decimal places to display
    acceleration : float, optional
        Acceleration in units/s^2
    resolution : float, optional
        Motor resolution
    user_limits : tuple, optional
        (low_limit, high_limit) for motion
    tick_rate_hz : float, optional
        Update rate for the simulation
    value : float, optional
        Initial position value
    """

    # Additional control signals
    resolution = pvproperty(name=".MRES", value=0.0, doc="Motor Step Size (EGU)")
    encoder = pvproperty(name=".REP", value=0, doc="Raw Encoder Position")
    clr_enc_lss = pvproperty(
        name="_ENC_LSS_CLR_CMD.PROC", value=0, doc="Clear encoder loss command"
    )
    home_cmd = pvproperty(name="_HOME_CMD.PROC", value=0, doc="Home command")
    enable = pvproperty(name="_ENA_CMD.PROC", value=0, doc="Enable command")
    kill = pvproperty(name="_KILL_CMD.PROC", value=0, doc="Kill command")

    # Status signals with ai record type for DESC field
    mtact = pvproperty(name="_MTACT_STS", value=0, record="ai", doc="Motor Active")
    mlim = pvproperty(name="_MLIM_STS", value=0, record="ai", doc="Minus Limit")
    plim = pvproperty(name="_PLIM_STS", value=0, record="ai", doc="Plus Limit")
    ampen = pvproperty(name="_AMPEN_STS", value=0, record="ai", doc="Amplifier Enabled")
    inpos = pvproperty(name="_INPOS_STS", value=0, record="ai", doc="In Position")
    enc_lss = pvproperty(name="_ENC_LSS_STS", value=0, record="ai", doc="Encoder Loss")
    loopm = pvproperty(name="_LOOPM_STS", value=0, record="ai", doc="Loop Mode")
    tiact = pvproperty(name="_TIACT_STS", value=0, record="ai", doc="Time Active")
    intmo = pvproperty(
        name="_INTMO_STS", value=0, record="ai", doc="Interpolation Mode"
    )
    dwpro = pvproperty(name="_DWPRO_STS", value=0, record="ai", doc="Dwell Process")
    daerr = pvproperty(name="_DAERR_STS", value=0, record="ai", doc="DAC Error")
    dvzer = pvproperty(name="_DVZER_STS", value=0, record="ai", doc="Drive Zero")
    abdec = pvproperty(
        name="_ABDEC_STS", value=0, record="ai", doc="Abort Deceleration"
    )
    uwpen = pvproperty(
        name="_UWPEN_STS", value=0, record="ai", doc="User Write Pending"
    )
    uwsen = pvproperty(name="_UWSEN_STS", value=0, record="ai", doc="User Write Sent")
    errtg = pvproperty(name="_ERRTG_STS", value=0, record="ai", doc="Error Trigger")
    swpoc = pvproperty(
        name="_SWPOC_STS", value=0, record="ai", doc="Software Position Compare"
    )
    asscs = pvproperty(name="_ASSCS_STS", value=0, record="ai", doc="Axis State Status")
    frpos = pvproperty(
        name="_FRPOS_STS", value=0, record="ai", doc="Following Error Position"
    )
    hsrch = pvproperty(name="_HSRCH_STS", value=0, record="ai", doc="Home Search")
    sodpl = pvproperty(
        name="_SODPL_STS", value=0, record="ai", doc="Software Overtravel Disable"
    )
    sopl = pvproperty(
        name="_SOPL_STS", value=0, record="ai", doc="Software Position Limit"
    )
    hocpl = pvproperty(name="_HOCPL_STS", value=0, record="ai", doc="Home Complete")
    phsra = pvproperty(
        name="_PHSRA_STS", value=0, record="ai", doc="Phase Reference Active"
    )
    prefe = pvproperty(
        name="_PREFE_STS", value=0, record="ai", doc="Position Reference Error"
    )
    trmov = pvproperty(name="_TRMOV_STS", value=0, record="ai", doc="Trigger Move")
    iffe = pvproperty(name="_IFFE_STS", value=0, record="ai", doc="In Following Error")
    amfae = pvproperty(
        name="_AMFAE_STS", value=0, record="ai", doc="Amplifier Fault Error"
    )
    amfe = pvproperty(name="_AMFE_STS", value=0, record="ai", doc="Amplifier Fault")
    fafoe = pvproperty(
        name="_FAFOE_STS", value=0, record="ai", doc="Fatal Following Error"
    )
    wfoer = pvproperty(
        name="_WFOER_STS", value=0, record="ai", doc="Warning Following Error"
    )

    def __init__(self, prefix, **kwargs):
        super().__init__(prefix, **kwargs)

    @home_cmd.putter
    async def home_cmd(self, instance, value):
        """Simulate homing command."""
        if value == 1:
            # Reset to 0 after brief delay
            await asyncio.sleep(0.1)
            await instance.write(0)
            await self.motor.write(0)
        return value

    @clr_enc_lss.putter
    async def clr_enc_lss(self, instance, value):
        """Simulate encoder loss clear command."""
        if value == 1:
            await self.enc_lss.write(0)
            await asyncio.sleep(0.1)
            await instance.write(0)
        return value
