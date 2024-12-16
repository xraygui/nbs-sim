import textwrap
import time

import numpy as np
from scipy.special import erf
from caproto.server import (
    PVGroup,
    SubGroup,
    ioc_arg_parser,
    pvproperty,
    run,
    PvpropertyDouble,
)
from caproto.ioc_examples.fake_motor_record import FakeMotor
from caproto import ChannelType
from os.path import join, dirname


class QuadSlits(PVGroup):
    """
    A simulation of SST 4-blade slits.

    This simulates the following motors:
    - Top blade
    - Bottom blade
    - Inboard blade
    - Outboard blade

    And calculates transmission based on the total opening area.
    """

    # The real (or physical) positioners
    top = SubGroup(FakeMotor, velocity=2, precision=3, prefix="T}Mtr")
    bottom = SubGroup(FakeMotor, velocity=2, precision=3, prefix="B}Mtr")
    inboard = SubGroup(FakeMotor, velocity=2, precision=3, prefix="I}Mtr")
    outboard = SubGroup(FakeMotor, velocity=2, precision=3, prefix="O}Mtr")

    # Transmission through the slits
    transmission = pvproperty(
        value=0.0,
        dtype=float,
        read_only=True,
        doc="Total beam transmission through slits",
    )

    def __init__(self, prefix, *, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        # Parameters for transmission calculation
        self.min_opening = 0.1  # mm, minimum opening for any transmission
        self.max_opening = 5.0  # mm, opening for maximum transmission

    def _calc_size(self, pos1, pos2):
        """Helper to calculate opening size from two blade positions"""
        return abs(pos1 - pos2)

    @transmission.scan(period=0.1)
    async def transmission(self, instance, async_lib):
        """Calculate total transmission through slits"""
        # Calculate current openings
        v_size = self._calc_size(
            self.top.motor.field_inst.user_readback_value.value,
            self.bottom.motor.field_inst.user_readback_value.value,
        )
        h_size = self._calc_size(
            self.outboard.motor.field_inst.user_readback_value.value,
            self.inboard.motor.field_inst.user_readback_value.value,
        )

        # Calculate transmission for each direction
        def calc_transmission(size):
            if size < self.min_opening:
                return 0.0
            elif size > self.max_opening:
                return 1.0
            else:
                # Linear ramp between min and max
                return (size - self.min_opening) / (self.max_opening - self.min_opening)

        v_trans = calc_transmission(v_size)
        h_trans = calc_transmission(h_size)

        # Total transmission is product of both directions
        total_trans = v_trans * h_trans
        await instance.write(value=total_trans)


class Slit(FakeMotor):
    """A slit simulation device."""

    transmission = pvproperty(
        value=0,
        dtype=float,
        read_only=True,
        doc="Transmission through slit",
    )

    @transmission.scan(period=0.05)
    async def transmission(self, instance, async_lib):
        value = await self._read()
        await self.transmission.write(value=value)

    def __init__(
        self,
        *args,
        trans_min,
        trans_max,
        velocity=10,
        precision=3,
        user_limits,
        parent=None,
        **kwargs
    ):
        """
        trans_min: Minimum opening for slit to transmit beam
        trans_max: Opening where transmission is maximum
        """
        super().__init__(
            *args,
            velocity=velocity,
            precision=precision,
            user_limits=user_limits,
            parent=None
        )
        self.trans_min = trans_min
        self.trans_max = trans_max

    async def _read(self):
        rbv = self.motor.field_inst.user_readback_value.value
        if rbv < self.trans_min:
            return 0
        if rbv > self.trans_max:
            return 1
        else:
            return (rbv - self.trans_min) / (self.trans_max - self.trans_min)
