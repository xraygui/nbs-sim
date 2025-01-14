"""
Simulated mirror devices for SST-1.
"""

from caproto import ChannelType
from caproto.server import PVGroup, pvproperty, SubGroup
from .motors import DelayedFakePositioner, FakePositioner
import asyncio


class MirrorAxis(FakePositioner):
    """
    Mirror axis with appropriate PV names.
    """

    setpoint = pvproperty(name="}Mtr_SP", value=0)
    readback = pvproperty(name="}Mtr_MON", value=0, read_only=True)


class FMBMirrorAxis(DelayedFakePositioner):
    """
    FMB mirror axis with appropriate PV names.
    """

    setpoint = pvproperty(name="}Mtr_POS_SP", value=0)
    readback = pvproperty(name="}Mtr_MON", value=0, read_only=True)


class HexapodMirror(PVGroup):
    """
    Simulation of a hexapod mirror with 6 degrees of freedom.
    """

    x = SubGroup(MirrorAxis, prefix="X")
    y = SubGroup(MirrorAxis, prefix="Y")
    z = SubGroup(MirrorAxis, prefix="Z")
    roll = SubGroup(MirrorAxis, prefix="R")
    pitch = SubGroup(MirrorAxis, prefix="P")
    yaw = SubGroup(MirrorAxis, prefix="Yaw")

    def __init__(self, prefix, *, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)


class FMBHexapodMirror(PVGroup):
    """
    Simulation of an FMB hexapod mirror with 6 degrees of freedom.
    """

    # Status PVs
    busy = pvproperty(value=0, name="}BUSY_STS", dtype=ChannelType.LONG)
    move_cmd = pvproperty(value=0, name="}MOVE_CMD.PROC", dtype=ChannelType.LONG)
    stop_cmd = pvproperty(value=0, name="}STOP_CMD.PROC", dtype=ChannelType.LONG)

    # Axis components
    x = SubGroup(FMBMirrorAxis, prefix="-Ax:X")
    y = SubGroup(FMBMirrorAxis, prefix="-Ax:Y")
    z = SubGroup(FMBMirrorAxis, prefix="-Ax:Z")
    roll = SubGroup(FMBMirrorAxis, prefix="-Ax:R")
    pitch = SubGroup(FMBMirrorAxis, prefix="-Ax:P")
    yaw = SubGroup(FMBMirrorAxis, prefix="-Ax:Yaw")

    def __init__(self, prefix, *, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)

    @move_cmd.putter
    async def move_cmd(self, instance, value):
        """Process a move command by moving all axes."""
        if value == 1:
            await self.busy.write(1)
            # Start all moves
            axes = [self.x, self.y, self.z, self.roll, self.pitch, self.yaw]
            tasks = [axis.start_motion() for axis in axes]
            # Wait for all moves to complete
            await asyncio.gather(*tasks)
            await self.busy.write(0)
        return value

    @stop_cmd.putter
    async def stop_cmd(self, instance, value):
        """Process a stop command by canceling all moves."""
        if value == 1:
            axes = [self.x, self.y, self.z, self.roll, self.pitch, self.yaw]
            for axis in axes:
                if axis._move_task is not None:
                    axis._move_task.cancel()
            await self.busy.write(0)
        return value
