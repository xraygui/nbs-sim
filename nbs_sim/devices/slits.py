import asyncio

import textwrap
import time

import numpy as np
from scipy.special import erf
from caproto.server import PVGroup, SubGroup, ioc_arg_parser, pvproperty, run, PvpropertyDouble
from caproto.ioc_examples.fake_motor_record import FakeMotor
from caproto import ChannelType
from os.path import join, dirname


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

    def __init__(self, trans_min, trans_max, *args, **kwargs):
        """
        trans_min: Minimum opening for slit to transmit beam
        trans_max: Opening where transmission is maximum
        """
        super().__init__(*args, **kwargs)
        self.trans_min = trans_min
        self.trans_max = trans_max

    async def _read(self):
        rbv = self.motor.field_inst.user_readback_value.value
        if rbv < self.trans_min:
            return 0
        if rbv > self.trans_max:
            return 1
        else:
            return (rbv - self.trans_min)/(self.trans_max - self.trans_min)
