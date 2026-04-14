from multiprocessing import Value
from caproto.server import PVGroup, pvproperty
import numpy as np


class K2600B(PVGroup):
    """
    Caproto simulation for a Keithley 2600-series style SMU (haxpes SMU device).

    Exposes the PV suffixes used by ``haxpes.devices.k2600b.SMU``. Read/write
    pairs are loosely coupled: setpoints update matching readbacks with static
    defaults for measured quantities.

    Parameters
    ----------
    prefix : str
        IOC prefix (e.g. ``XF:07ID1{K2601B:1}``).
    parent : object, optional
        Parent beamline group, if any.
    """

    sp_lim_v = pvproperty(name="SP-LimV", value=10.0, dtype=float)
    sp_lim_i = pvproperty(name="SP-LimI", value=0.01, dtype=float)

    sour_sts = pvproperty(name="Sour:Sts", value=1, dtype=int, read_only=True)
    sour_sel = pvproperty(name="Sour-Sel", value=1, dtype=int)

    sts_out_ena = pvproperty(name="Sts:Out-Ena", value=1, dtype=int, read_only=True)
    cmd_out_ena = pvproperty(name="Cmd:Out-Ena", value=1, dtype=int)

    rb_vlvl = pvproperty(name="RB-VLvl", value=0.0, dtype=float, read_only=True, precision=3)
    sp_vlvl = pvproperty(name="SP-VLvl", value=0.0, dtype=float, precision=3)

    rb_ilvl = pvproperty(name="RB-ILvl", value=0.0, dtype=float, read_only=True, precision=3)
    sp_ilvl = pvproperty(name="SP-ILvl", value=0.0, dtype=float, precision=3)

    rb_meas_v = pvproperty(name="RB-MeasV", value=0.0, dtype=float, read_only=True, precision=3)
    rb_meas_i = pvproperty(name="RB-MeasI", value=0.0, dtype=float, read_only=True, precision=3)

    sts_meas_irang = pvproperty(
        name="Sts-MeasIRang", value=0.0, dtype=float, read_only=True
    )
    sp_meas_irang = pvproperty(name="SP-MeasIRang", value=0.0, dtype=float)

    sts_sour_vrang = pvproperty(
        name="Sts-SourVRang", value=0.0, dtype=float, read_only=True
    )
    sp_sour_vrang = pvproperty(name="SP-SourVRang", value=0.0, dtype=float)

    sts_sour_irang = pvproperty(
        name="Sts-SourIRang", value=0.0, dtype=float, read_only=True
    )
    sp_sour_irang = pvproperty(name="SP-SourIRang", value=0.0, dtype=float)

    sp_sour_auto_rang_i = pvproperty(name="SP-SourAutoRangI", value=0, dtype=int)
    sp_sour_auto_rang_v = pvproperty(name="SP-SourAutoRangV", value=0, dtype=int)
    sp_meas_auto_rang_i = pvproperty(name="SP-MeasAutoRangI", value=0, dtype=int)
    sp_meas_auto_rang_v = pvproperty(name="SP-MeasAutoRangV", value=0, dtype=int)

    @sour_sel.putter
    async def sour_sel(self, instance, value):
        await self.sour_sts.write(value)
        return value

    @cmd_out_ena.putter
    async def cmd_out_ena(self, instance, value):
        await self.sts_out_ena.write(int(value))
        if value == 0:
            await self.rb_meas_v.write(0)
            await self.rb_meas_i.write(0)
        else:
            await self.rb_meas_v.write(self.rb_vlvl.value)
            await self.rb_meas_i.write(self.rb_ilvl.value)
        return value

    @sp_vlvl.putter
    async def sp_vlvl(self, instance, value):
        await self.rb_vlvl.write(value)

        return value

    @sp_ilvl.putter
    async def sp_ilvl(self, instance, value):
        await self.rb_ilvl.write(value)
        if self.sts_out_ena.value == 1:
            await self.rb_meas_v.write(value)
        else:
            await self.rb_meas_v.write(0)
        return value

    @sp_meas_irang.putter
    async def sp_meas_irang(self, instance, value):
        await self.sts_meas_irang.write(value)
        return value

    @sp_sour_vrang.putter
    async def sp_sour_vrang(self, instance, value):
        await self.sts_sour_vrang.write(value)
        return value

    @sp_sour_irang.putter
    async def sp_sour_irang(self, instance, value):
        await self.sts_sour_irang.write(value)
        return value

    @sp_vlvl.startup
    async def sp_vlvl(self, instance, async_lib):
        await self.rb_vlvl.write(instance.value)
        await self.rb_meas_v.write(instance.value)

    @sp_ilvl.startup
    async def sp_ilvl(self, instance, async_lib):
        await self.rb_ilvl.write(instance.value)

    @sour_sel.startup
    async def sour_sel(self, instance, async_lib):
        await self.sour_sts.write(instance.value)

    @cmd_out_ena.startup
    async def cmd_out_ena(self, instance, async_lib):
        await self.sts_out_ena.write(instance.value)

    @sp_meas_irang.startup
    async def sp_meas_irang(self, instance, async_lib):
        await self.sts_meas_irang.write(instance.value)

    @sp_sour_vrang.startup
    async def sp_sour_vrang(self, instance, async_lib):
        await self.sts_sour_vrang.write(instance.value)

    @sp_sour_irang.startup
    async def sp_sour_irang(self, instance, async_lib):
        await self.sts_sour_irang.write(instance.value)

    @rb_meas_v.scan(period=0.1)
    async def rb_meas_v(self, instance, async_lib):
        if self.sts_out_ena.value == 1:
            value = np.random.normal(self.rb_vlvl.value, 0.1)
            await instance.write(value)
        else:
            await instance.write(0)

    @rb_meas_i.scan(period=0.1)
    async def rb_meas_i(self, instance, async_lib):
        if self.sts_out_ena.value == 1:
            value = np.random.normal(self.rb_ilvl.value, 0.1)
            await instance.write(value * 1e-9)
        else:
            await instance.write(0)
