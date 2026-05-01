from caproto.server import PVGroup, pvproperty, SubGroup

class PCOEdgeCam(PVGroup):
    adc_mode = pvproperty(value=0, name="AdcMode")
    adc_mode_RBV = pvproperty(value=0, name="AdcMode_RBV", read_only=True)
    camera_setup = pvproperty(value=0, name="CameraSetup")
    camera_setup_RBV = pvproperty(value=0, name="CameraSetup_RBV", read_only=True)
    readout_mode = pvproperty(value=0, name="ReadoutMode")
    readout_mode_RBV = pvproperty(value=0, name="ReadoutMode_RBV", read_only=True)
    bit_alignment = pvproperty(value=0, name="BitAlignment")
    bit_alignment_RBV = pvproperty(value=0, name="BitAlignment_RBV", read_only=True)
    pixel_rate = pvproperty(value=0, name="PixelRate")
    pixel_rate_RBV = pvproperty(value=0, name="PixelRate_RBV", read_only=True)
    delay_time = pvproperty(value=0, name="DelayTime")
    delay_time_RBV = pvproperty(value=0, name="DelayTime_RBV", read_only=True)

    @adc_mode.putter
    async def adc_mode(self, instance, value):
        await self.adc_mode_RBV.write(value)

    @camera_setup.putter
    async def camera_setup(self, instance, value):
        await self.camera_setup_RBV.write(value)

    @readout_mode.putter
    async def readout_mode(self, instance, value):
        await self.readout_mode_RBV.write(value)

    @bit_alignment.putter
    async def bit_alignment(self, instance, value):
        await self.bit_alignment_RBV.write(value)

    @pixel_rate.putter
    async def pixel_rate(self, instance, value):
        await self.pixel_rate_RBV.write(value)

    @delay_time.putter
    async def delay_time(self, instance, value):
        await self.delay_time_RBV.write(value)

class PCOEdgeDetector(PVGroup):
    cam = SubGroup(PCOEdgeCam, prefix="cam1:")

    def __init__(self, prefix, *, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)