from caproto.server import PVGroup, pvproperty
from caproto import SkipWrite


class HAXFloodgun(PVGroup):
    energy_rbv = pvproperty(value=0, dtype=float, name="EnergyRBV", read_only=True)
    energy_sp = pvproperty(value=0, dtype=float, name="EnergySP")
    vgrid_rbv = pvproperty(value=0, dtype=float, name="VgridRBV", read_only=True)
    vgrid_sp = pvproperty(value=0, dtype=float, name="VgridSP")
    iemis = pvproperty(value=0, dtype=float, name="IemissionRBV", read_only=True)
    startProc = pvproperty(value=0, dtype=int, name="Resume")
    stopProc = pvproperty(value=0, dtype=int, name="Shutdown")

    @energy_sp.putter
    async def energy_sp(self, instance, value):
        await self.instance.write(value, verify_value=False)
        await self.energy_rbv.write(value=value)

    @vgrid_sp.putter
    async def vgrid_sp(self, instance, value):
        await self.instance.write(value, verify_value=False)
        await self.vgrid_rbv.write(value=value)
