from caproto.server import PVGroup, pvproperty
import asyncio
import numpy as np
from caproto.ioc_examples.fake_motor_record import (
    broadcast_precision_to_fields,
    motor_record_simulator,
)


async def enhanced_motor_record_simulator(
    instance, async_lib, defaults=None, tick_rate_hz=10.0
):
    """
    An enhanced motor record simulator with proper acceleration support.

    Parameters
    ----------
    instance : pvproperty (ChannelDouble)
        Ensure you set ``record='motor'`` in your pvproperty first.

    async_lib : AsyncLibraryLayer

    defaults : dict, optional
        Defaults for velocity, precision, acceleration, limits, and resolution.

    tick_rate_hz : float, optional
        Update rate in Hz.
    """
    if defaults is None:
        defaults = dict(
            velocity=1,
            precision=3,
            acceleration=1.0,
            resolution=1e-6,
            tick_rate_hz=10.0,
            user_limits=(0.0, 100.0),
            settling_time=0.0,
        )

    fields = instance.field_inst
    have_new_position = False

    async def value_write_hook(fields, value):
        nonlocal have_new_position
        # This happens when a user puts to `motor.VAL`
        have_new_position = True

    fields.value_write_hook = value_write_hook

    await instance.write_metadata(precision=defaults["precision"])
    await broadcast_precision_to_fields(instance)

    await fields.velocity.write(defaults["velocity"])
    await fields.seconds_to_velocity.write(defaults["acceleration"])
    await fields.motor_step_size.write(defaults["resolution"])
    await fields.user_low_limit.write(defaults["user_limits"][0])
    await fields.user_high_limit.write(defaults["user_limits"][1])

    while True:
        dwell = 1.0 / tick_rate_hz
        target_pos = instance.value
        current_pos = fields.user_readback_value.value
        diff = target_pos - current_pos

        if abs(diff) < 1e-9 and not have_new_position:
            if fields.stop.value != 0:
                await fields.stop.write(0)
            await async_lib.library.sleep(dwell)
            continue

        if fields.stop.value != 0:
            await fields.stop.write(0)

        await fields.done_moving_to_value.write(0)
        await fields.motor_is_moving.write(1)

        # Calculate motion profile with acceleration
        velocity = fields.velocity.value
        time_to_full_velocity = fields.seconds_to_velocity.value
        if time_to_full_velocity == 0:
            acceleration = 0
        else:
            acceleration = velocity / time_to_full_velocity

        # Calculate motion parameters
        distance = abs(diff)
        if distance > 0 and velocity > 0 and acceleration > 0:
            # Calculate time to reach full velocity

            # Calculate distance covered during acceleration
            accel_distance = 0.5 * acceleration * time_to_full_velocity**2

            # Check if we can reach full velocity
            if distance <= 2 * accel_distance:
                # Triangular profile - can't reach full velocity
                time_to_full_velocity = np.sqrt(distance / acceleration)
                max_velocity = acceleration * time_to_full_velocity
                total_time = 2 * time_to_full_velocity
            else:
                # Trapezoidal profile - can reach full velocity
                max_velocity = velocity
                constant_distance = distance - 2 * accel_distance
                constant_time = constant_distance / velocity
                total_time = 2 * time_to_full_velocity + constant_time
        else:
            # No acceleration or no movement
            total_time = distance / velocity if velocity > 0 else 0
            max_velocity = velocity
            time_to_full_velocity = 0

        # Calculate number of steps
        num_steps = int(total_time // dwell)
        if num_steps <= 0:
            num_steps = 1

        step_size = diff / num_steps
        resolution = max((fields.motor_step_size.value, 1e-10))
        print(
            f"num_steps: {num_steps}, step_size: {step_size}, resolution: {resolution}, time_to_full_velocity: {time_to_full_velocity}, max_velocity: {max_velocity}, total_time: {total_time}, diff: {diff}"
        )
        for step in range(num_steps):
            if fields.stop.value != 0:
                await fields.stop.write(0)
                await instance.write(current_pos)
                break
            if fields.stop_pause_move_go.value == "Stop":
                await instance.write(current_pos)
                break

            # Calculate current velocity based on motion profile
            if total_time > 0:
                current_time = step * dwell
                if current_time <= time_to_full_velocity:
                    # Acceleration phase
                    current_velocity = acceleration * current_time
                elif current_time >= (total_time - time_to_full_velocity):
                    # Deceleration phase
                    decel_time = total_time - current_time
                    current_velocity = acceleration * decel_time
                else:
                    # Constant velocity phase
                    current_velocity = max_velocity
            else:
                current_velocity = 0

            # Update position
            current_pos += step_size
            raw_readback = current_pos / resolution

            await fields.user_readback_value.write(current_pos)
            await fields.dial_readback_value.write(current_pos)
            await fields.raw_readback_value.write(raw_readback)

            await async_lib.library.sleep(dwell)
        else:
            # Only executed if we didn't break
            if defaults.get("settling_time", 0.0) > 0:
                await async_lib.library.sleep(defaults.get("settling_time", 0.0))
            await fields.user_readback_value.write(target_pos)

        await fields.motor_is_moving.write(0)
        await fields.done_moving_to_value.write(1)
        have_new_position = False


class FakeMotor(PVGroup):
    """Standard EPICS Motor Record simulation."""

    motor = pvproperty(value=0.0, name="", record="motor", precision=3)

    def __init__(
        self,
        prefix,
        velocity=1.0,
        precision=3,
        acceleration=0.25,
        resolution=1e-6,
        user_limits=(0.0, 100.0),
        tick_rate_hz=10.0,
        value=0,
        parent=None,
        settling_time=0.0,
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
            "settling_time": settling_time,
        }

    @motor.startup
    async def motor(self, instance, async_lib):
        # Start the simulator:
        await instance.write(self.initial_value)
        await enhanced_motor_record_simulator(
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
