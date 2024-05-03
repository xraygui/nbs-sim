import asyncio
from caproto.server import PVGroup, pvproperty


class SSTShutter(PVGroup):
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
