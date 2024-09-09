from caproto.server import (
    PVGroup,
    pvproperty,
)


class RingCurrent(PVGroup):
    current = pvproperty(
        value=0, dtype=float, read_only=True, doc="Ring Current", name=""
    )

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)

    @current.scan(period=0.1)
    async def current(self, instance, async_lib):
        value = self.parent.current_func()
        await instance.write(value=value)
