from caproto.server import PVGroup, pvproperty, SubGroup

class GreatEyesCam(PVGroup):
    adc_speed = pvproperty(value=0, name="GreatEyesAdcSpeed")
    adc_speed_RBV = pvproperty(value=0, name="GreatEyesAdcSpeed_RBV", read_only=True)

    capacity = pvproperty(value=0, name="GreatEyesCapacity")
    capacity_RBV = pvproperty(value=0, name="GreatEyesCapacity_RBV", read_only=True)

    enable_cooling = pvproperty(value=0, name="GreatEyesEnableCooling")
    enable_cooling_RBV = pvproperty(value=0, name="GreatEyesEnableCooling_RBV", read_only=True)

    gain = pvproperty(value=0, name="GreatEyesGain")
    gain_RBV = pvproperty(value=0, name="GreatEyesGain_RBV", read_only=True)

    hot_side_temp = pvproperty(value=30.0, name="GreatEyesHotSideTemp", read_only=True)

    readout_dir = pvproperty(value=0, name="GreatEyesReadoutDir")
    readout_dir_RBV = pvproperty(value=0, name="GreatEyesReadoutDir_RBV", read_only=True)

    sync = pvproperty(value=0, name="GreatEyesSync")
    sync_RBV = pvproperty(value=0, name="GreatEyesSync_RBV", read_only=True)

    # Setters to update the RBV when the setpoint PV is set

    @adc_speed.putter
    async def adc_speed(self, instance, value):
        await self.adc_speed_RBV.write(value)
        return value

    @capacity.putter
    async def capacity(self, instance, value):
        await self.capacity_RBV.write(value)
        return value

    @enable_cooling.putter
    async def enable_cooling(self, instance, value):
        await self.enable_cooling_RBV.write(value)
        return value

    @gain.putter
    async def gain(self, instance, value):
        await self.gain_RBV.write(value)
        return value

    @readout_dir.putter
    async def readout_dir(self, instance, value):
        await self.readout_dir_RBV.write(value)
        return value

    @sync.putter
    async def sync(self, instance, value):
        await self.sync_RBV.write(value)
        return value
        

class GreatEyes(PVGroup):
    cam = SubGroup(GreatEyesCam, prefix="cam1:")

    def __init__(self, prefix, *, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)