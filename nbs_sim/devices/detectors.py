import asyncio

import textwrap
import time

import numpy as np
from scipy.special import erf
from caproto.server import PVGroup, SubGroup, ioc_arg_parser, pvproperty, run, PvpropertyDouble
from caproto import ChannelType
from os.path import join, dirname
from scipy.interpolate import UnivariateSpline


class SSTADCBase(PVGroup):
    Volt = pvproperty(value=0, dtype=float, read_only=True, doc="ADC Value")
    sigma = 0.05

    def __init__(self, prefix, kind="sc", **kwargs):
        super().__init__(prefix, **kwargs)
        self.kind = kind
        
    @Volt.scan(period=0.5)
    async def Volt(self, instance, async_lib):
        value = await self._read()
        v = np.random.normal(value, self.sigma)
        await instance.write(value=v)


class DetectorKindMixin:
    async def _read(self):
        if self.kind == "i0":
            intensity = self.parent.intensity_func()
            return intensity
        elif self.kind == "sc":
            energy = self.parent.energy
            overlap = self.parent.distance_func(transmission=False)
            intensity = self.parent.intensity_func()*self.parent.yspl(energy)
            return intensity*overlap
        elif self.kind = "ref":
            energy = self.parent.energy
            intensity = self.parent.intensity_func()*self.parent.refspl(energy)
            return intensity
        elif self.kind == "i1":
            overlap = self.parent.distance_func(transmission=True)
            intensity = self.parent.intensity_func()
            return intensity*overlap
            
class SSTADC(SSTADCBase, DetectorKindMixin):
    pass
