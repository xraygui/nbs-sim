#!/usr/bin/env python3
"""
This example is quite large. It defines a range of simulated detectors and
motors and is used for demos and tutorials.
"""
import asyncio

import textwrap
import time

import numpy as np
from scipy.special import erf
from caproto.server import PVGroup, SubGroup, ioc_arg_parser, pvproperty, run, PvpropertyDouble
from caproto.ioc_examples.fake_motor_record import FakeMotor
from caproto import ChannelType
from .manipulator import Manipulator, MultiMesh
from .energy import Energy
from .caproto_mca import MCASIM
from os.path import join, dirname
from scipy.interpolate import UnivariateSpline


def norm_erf(x, width=1):
    return 0.5*(erf(2.0*x/width) + 1)


class _ADCBase(PVGroup):
    Volt = pvproperty(value=0, dtype=float, read_only=True, doc="ADC Value")
    sigma = 0.05

    @Volt.scan(period=0.5)
    async def Volt(self, instance, async_lib):
        value = await self._read()
        v = np.random.normal(value, self.sigma)
        await instance.write(value=v)


class I0(_ADCBase):
    async def _read(self):
        intensity = self.parent.intensity_func()
        return intensity


class Ref(_ADCBase):
    async def _read(self):
        energy = self.parent.energy.mono.mono.readback.value
        intensity = self.parent.intensity_func()*self.parent.refspl(energy)
        return intensity


class SC(_ADCBase):
    async def _read(self):
        energy = self.parent.energy.mono.mono.readback.value
        overlap = self.parent.distance_func(transmission=False)
        intensity = self.parent.intensity_func()*self.parent.yspl(energy)
        return intensity*overlap


class I1(_ADCBase):
    async def _read(self):
        overlap = self.parent.distance_func(transmission=True)
        intensity = self.parent.intensity_func()
        return intensity*overlap

class Shutter(PVGroup):
    state = pvproperty(
        value=0,
        dtype=int,
        read_only=True,
        name="Pos-Sts")
    cls = pvproperty(
        value=0,
        dtype=int,
        name="Cmd:Cls-Cmd")
    opn = pvproperty(
        value=0,
        dtype=int,
        name="Cmd:Opn-Cmd")
    error = pvproperty(
        value=0,
        dtype=int,
        name="Err-Sts")
    transmission = pvproperty(value=0, dtype=float, read_only=True)

    def __init__(self, delay=0.5, openval=0, closeval=1, **kwargs):
        super().__init__(**kwargs)
        self._delay = delay
        self._openval = openval
        self._closeval = closeval

    @opn.startup
    async def opn(self, instance, async_lib):
        await self.state.write(value=self._openval)
        await self.transmission.write(value=1)

    @cls.putter
    async def cls(self, instance, value):
        await asyncio.sleep(self._delay)
        await self.state.write(value=self._closeval)
        await self.transmission.write(value=0)

    @opn.putter
    async def opn(self, instance, value):
        await asyncio.sleep(self._delay)
        await self.state.write(value=self._openval)
        await self.transmission.write(value=1)


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


class Beamline(PVGroup):
    """
    A collection of detectors coupled to motors and an oscillating beam
    current.

    An IOC that provides a simulated pinhole, edge and slit with coupled with a
    shared global current that oscillates in time.
    """

    N_per_I_per_s = 200

    current = pvproperty(value=500.0, dtype=PvpropertyDouble, read_only=True, precision=2)
    endstation = pvproperty(value="UCAL", enum_strings=["RSoXS", "NEXAFS", "LARIAT", "LARIAT II", "UCAL", "HAXPES", "VPEEM", "pending", "conflict", "none"], record="mbbo", dtype=ChannelType.ENUM, name="Endstn-Sel")
    status = pvproperty(value="OK", enum_strings=["OK", "DUMPED", "FILLING"], record='mbbo', dtype=ChannelType.ENUM)
    i0 = SubGroup(I0, doc="i0")
    i1 = SubGroup(I1, doc="i1")
    sc = SubGroup(SC, doc="sc")
    ref = SubGroup(Ref, doc="ref")

    eslit = SubGroup(Slit, trans_min=10, trans_max=40, velocity=10, precision=3,
                     user_limits=(0, 10), doc="Simulated slit")
    i0upAu = SubGroup(FakeMotor, doc="i0 Up")
    tesz = SubGroup(FakeMotor, doc="tesz")
    psh1 = SubGroup(Shutter, doc="Front End Shutter")
    psh4 = SubGroup(Shutter, doc="Front End Shutter")
    psh7 = SubGroup(Shutter, doc="Simulated shutter")
    psh10 = SubGroup(Shutter, doc="Simulated shutter")
    manipulator = SubGroup(Manipulator, doc="Simulated 4-axis Manipulator")
    multimesh = SubGroup(MultiMesh, doc="Simulated MultiMesh Manipulator")
    energy = SubGroup(Energy, doc="Simulated Energy Object")
    tesmca = SubGroup(MCASIM, doc="Simulated TES MCA")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transmission_list = []
        self.transmission_list.append(self.eslit)
        self.transmission_list.append(self.psh4)
        self.transmission_list.append(self.psh7)
        self.transmission_list.append(self.psh10)
        dirpath = dirname(__file__)
        print(dirpath)
        data = np.load(join(dirpath, "all_edges.npz"))
        refdata = np.load(join(dirpath, "all_ref.npz"))
        self.yspl = UnivariateSpline(data['x'], data['y'], s=0)
        self.refspl = UnivariateSpline(refdata['x'], refdata['y'], s=0)

    async def __ainit__(self, async_lib):
        await self.tesz.motor.write(40)
        await self.eslit.motor.write(40)
        await self.energy.mono.mono.setpoint.write(400)
        await self.energy.gap.motor.write(32000)

    def current_func(self):
        t = time.monotonic()%(300)
        if t < 270:
            current = 500 - 50*t/270
        else:
            current = 500 - 50*(300 - t)/30
        return current

    def intensity_func(self):
        base = self.current_func()
        for trans_dev in self.transmission_list:
            base *= trans_dev.transmission.value
        return base

    def distance_func(self, transmission=False):
        dist = self.manipulator.distance_to_beam()
        if transmission:
            sgn = 1
        else:
            sgn = -1
        intensity = norm_erf(sgn*dist, 1)
        return intensity

    @current.scan(period=0.1)
    async def current(self, instance, async_lib):
        current = self.current_func()
        await instance.write(value=current)


def start():
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="SIM_SST:",
        desc=textwrap.dedent(Beamline.__doc__),
    )

    ioc = Beamline(**ioc_options)
    run(ioc.pvdb, startup_hook=ioc.__ainit__, **run_options)


if __name__ == "__main__":
    start()
