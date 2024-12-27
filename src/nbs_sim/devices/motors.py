from caproto.server import PVGroup, pvproperty
from caproto.ioc_examples.fake_motor_record import motor_record_simulator
import asyncio


class FakeMotor(PVGroup):
    """Standard EPICS Motor Record simulation."""

    motor = pvproperty(value=0.0, name="", record="motor", precision=3)

    def __init__(
        self,
        *args,
        velocity=0.1,
        precision=3,
        acceleration=1.0,
        resolution=1e-6,
        user_limits=(0.0, 100.0),
        tick_rate_hz=10.0,
        value=0,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
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
    """Simple positioner with only SP/RB interface."""

    setpoint = pvproperty(name="-SP", value=0)
    readback = pvproperty(name="-RB", value=0, read_only=True)

    def __init__(self, *args, value=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial_value = value

    @setpoint.startup
    async def setpoint(self, instance, async_lib):
        await instance.write(self.initial_value)
        await self.readback.write(self.initial_value)

    @setpoint.putter
    async def setpoint(self, instance, value):
        await instance.write(value, verify_value=False)
        await self.readback.write(value)
