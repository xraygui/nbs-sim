"""
export EPICS_CA_AUTO_ADDR_LIST=no
export EPICS_CAS_AUTO_BEACON_ADDR_LIST=no
export EPICS_CAS_BEACON_ADDR_LIST=10.66.51.255
export EPICS_CA_ADDR_LIST=10.66.51.255
"""


from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run
from caproto import ChannelType
import asyncio
import zmq.asyncio
import zmq
from textwrap import dedent
import time
import json
import numpy as np
import pickle
from os.path import exists
from scipy.stats import poisson, norm

class MCASIM(PVGroup):
    """
    A class to read ZMQ pulse info from TES
    """
    MAXBINS = 10000
    DEFAULT_LLIM = 200
    DEFAULT_ULIM = 1000
    DEFAULT_NBINS = 800
    COUNTS = pvproperty(value=0, record='ai', dtype=int, doc="ROI Counts")
    SPECTRUM = pvproperty(value=np.zeros(MAXBINS, dtype=int), dtype=int, doc="ROI Histogram")
    LLIM = pvproperty(value=DEFAULT_LLIM, record='ai', doc="ROI lower limit")
    ULIM = pvproperty(value=DEFAULT_ULIM, record='ai', doc='ROI upper limit')
    NBINS = pvproperty(value=DEFAULT_NBINS, record='ai', doc="ROI resolution")
    CENTERS = pvproperty(value=np.zeros(MAXBINS, dtype=float), dtype=float)
    COUNT_TIME = pvproperty(value=1.0, record='ai', doc='ROI Count Time')
    ACQUIRE = pvproperty(value=0, doc="ACQUIRE")
    LOAD_CAL = pvproperty(value=0)

    def __init__(self, *args, **kwargs):
        self._start_ts = time.time()
        self._poly_dict = {}
        self._bins = np.linspace(self.DEFAULT_LLIM, self.DEFAULT_ULIM, self.DEFAULT_NBINS + 1)
        super().__init__(*args, **kwargs)

    @ACQUIRE.putter
    async def ACQUIRE(self, instance, value):
        if value != 0:
            self._start_ts = time.time()
        return value

    @LLIM.putter
    async def LLIM(self, instance, value):
        self._bins = np.linspace(value, self.ULIM.value, self.NBINS.value + 1)
        centers = (self._bins[1:] + self._bins[:-1])*0.5
        await self.CENTERS.write(centers)

    @ULIM.putter
    async def ULIM(self, instance, value):
        self._bins = np.linspace(self.LLIM.value, value, self.NBINS.value + 1)
        centers = (self._bins[1:] + self._bins[:-1])*0.5
        await self.CENTERS.write(centers)

    @NBINS.putter
    async def NBINS(self, instance, value):
        if value > self.MAXBINS:
            value = self.MAXBINS
        self._bins = np.linspace(self.LLIM.value, self.ULIM.value, value + 1)
        centers = (self._bins[1:] + self._bins[:-1])*0.5
        await self.CENTERS.write(centers)

    @LOAD_CAL.putter
    async def LOAD_CAL(self, instance, value):
        pass
        # if value != 0:
        #    self.load_cal_file(self._cal_file_name)

    @CENTERS.startup
    async def CENTERS(self, instance, async_lib):
        centers = (self._bins[1:] + self._bins[:-1])*0.5
        await self.CENTERS.write(centers)

    @ACQUIRE.startup
    async def ACQUIRE(self, instance, async_lib):
        self._start_ts = time.time()

        while True:
            if self.ACQUIRE.value != 0 and self._start_ts + self.COUNT_TIME.value < time.time():
                overlap = self.parent.distance_func(transmission=False)
                energy = self.parent.energy.mono.mono.readback.value
                intensity = self.parent.intensity_func()*self.parent.yspl(energy)
                counts = poisson.rvs(overlap*intensity*norm.pdf(self.CENTERS.value, loc=energy, scale=1.5))
                counts += poisson.rvs(0.1*overlap*intensity*norm.pdf(self.CENTERS.value, loc=energy - 100, scale=1.5))
                
                await self.COUNTS.write(np.sum(counts))
                await self.SPECTRUM.write(counts)
                self._start_ts = time.time()
                if self.ACQUIRE.value > 0:
                    await self.ACQUIRE.write(self.ACQUIRE.value - 1)
            await async_lib.sleep(.05)

    """
    async def __ainit__(self, async_lib):
        print('* `__ainit__` startup hook called')
        if exists(self._cal_file_name):
            await self.LOAD_CAL.write(1)

        while True:
            msg = await self.socket.recv_multipart()
            data = self.decode_msg(msg)
            if self.ACQUIRE.value != 0:
                #if data['channum'] == 1:
                e = self.convert_to_energy(data)
                self._buffer.append(e)

    def decode_msg(self, msg):
        summaries = np.frombuffer(msg[0], dtype=self._dt1)
        return summaries

    def convert_to_energy(self, data):
        if self._cal_loaded:
            channum = data['channum'][0]
            try:
                return self._poly_dict[channum](data['pulseRMS'][0])
            except:
                return -1
        else:
            return -1    
    """
    
if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(default_prefix="XF:07ID-ES{{UCAL:ROIS}}:",
                                              desc = dedent(MCASIM.__doc__),
                                              supported_async_libs=('asyncio',))
    ioc = MCASIM(**ioc_options)
    run(ioc.pvdb, **run_options)
