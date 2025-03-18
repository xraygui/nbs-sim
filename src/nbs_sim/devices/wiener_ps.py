from .motors import FakePositioner
import asyncio
from caproto.server import PVGroup, SubGroup, pvproperty
import numpy as np


# -LV-u0} to -LV-u7}
# -HV-u300} to -HV-u307}
class WienerPSChannel(FakePositioner):
    """
    Simulated Wiener Power Supply Channel.

    Parameters
    ----------
    prefix : str
        The PV prefix for this channel
    value : float, optional
        Initial voltage value
    low_limit : float, optional
        Lower voltage limit
    high_limit : float, optional
        Upper voltage limit
    invert_readback : bool, optional
        If True, multiply readback by -1 (for LV channels)
    """

    setpoint = pvproperty(name="V-Set", value=0.0)
    readback = pvproperty(name="V-Sense", value=0.0, read_only=True)
    vrise = pvproperty(name="V-RiseRate", value=2.0)
    vfall = pvproperty(name="V-FallRate", value=2.0)
    current = pvproperty(name="I-Sense", value=0.0, read_only=True)
    current_limit = pvproperty(name="I-SetLimit", value=0.0)
    switch = pvproperty(name="Switch", value=1)

    def __init__(self, prefix, pos_polarity=True, **kwargs):
        # Initialize with 0 velocity - will be set dynamically based on rise/fall
        super().__init__(prefix, velocity=0.0, **kwargs)
        self._switch_enabled = True
        self._pos_polarity = pos_polarity

    @switch.putter
    async def switch(self, instance, value):
        """Handle switch state changes."""
        self._switch_enabled = bool(value)
        if not self._switch_enabled:
            await self.setpoint.write(0.0)
        return value

    @setpoint.putter
    async def setpoint(self, instance, value):
        """Handle setpoint changes considering switch state and rise/fall rates."""
        if not self._switch_enabled:
            return 0.0

        # Invert value for LV channels at the start
        target = value if self._pos_polarity else -np.abs(value)

        # Check limits
        if not (self.low_limit <= abs(target) <= self.high_limit):
            raise ValueError(
                f"Value {abs(target)} outside limits [{self.low_limit}, "
                f"{self.high_limit}]"
            )

        current = self.readback.value

        # Determine velocity based on whether we're rising or falling
        if abs(target) > abs(current):
            self.velocity = max(0.1, self.vrise.value)
        else:
            self.velocity = max(0.1, self.vfall.value)

        # Cancel any existing motion
        if self._move_task is not None and not self._move_task.done():
            self._move_task.cancel()
            try:
                await self._move_task
            except asyncio.CancelledError:
                pass

        # Start new motion
        self._move_task = asyncio.create_task(self._move_to(target))
        return value

    async def _move_to(self, target):
        """Override movement to handle switch state."""
        if not self._switch_enabled:
            await self.readback.write(0.0)
            return

        await super()._move_to(target)


class WienerPS(PVGroup):
    """
    Simulated Wiener Power Supply with 8 HV and 8 LV channels.

    The HV channels have prefix HV-u30X (X = 0-7) with range 0 to 3000V
    The LV channels have prefix LV-uX (X = 0-7) with range 0 to 300V
    LV channels have inverted readback values
    """

    lv_0 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u0}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )
    lv_1 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u1}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )
    lv_2 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u2}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )
    lv_3 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u3}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )
    lv_4 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u4}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )
    lv_5 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u5}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )
    lv_6 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u6}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )
    lv_7 = SubGroup(
        WienerPSChannel,
        prefix="-LV-u7}",
        low_limit=0,
        high_limit=300,
        pos_polarity=False,
    )

    hv_0 = SubGroup(WienerPSChannel, prefix="-HV-u300}", low_limit=0, high_limit=3000)
    hv_1 = SubGroup(WienerPSChannel, prefix="-HV-u301}", low_limit=0, high_limit=3000)
    hv_2 = SubGroup(WienerPSChannel, prefix="-HV-u302}", low_limit=0, high_limit=3000)
    hv_3 = SubGroup(WienerPSChannel, prefix="-HV-u303}", low_limit=0, high_limit=3000)
    hv_4 = SubGroup(WienerPSChannel, prefix="-HV-u304}", low_limit=0, high_limit=3000)
    hv_5 = SubGroup(WienerPSChannel, prefix="-HV-u305}", low_limit=0, high_limit=3000)
    hv_6 = SubGroup(WienerPSChannel, prefix="-HV-u306}", low_limit=0, high_limit=3000)
    hv_7 = SubGroup(WienerPSChannel, prefix="-HV-u307}", low_limit=0, high_limit=3000)

    def __init__(self, prefix, **kwargs):
        # Pop out channel name arguments
        channel_kwargs = {}
        for i in range(8):
            lv_name = kwargs.pop(f"lvch{i}", None)
            hv_name = kwargs.pop(f"hvch{i}", None)
            if lv_name is not None:
                channel_kwargs[f"lv_{i}_name"] = lv_name
            if hv_name is not None:
                channel_kwargs[f"hv_{i}_name"] = hv_name

        super().__init__(prefix, **kwargs)
