from caproto.server import PVGroup, pvproperty
from caproto.ioc_examples.fake_motor_record import motor_record_simulator
import asyncio
import numpy as np


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
