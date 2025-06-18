from caproto.server import PVGroup, pvproperty

low_freq_strings = ["   0.03 Hz", "   0.1 Hz", "   0.3 Hz", "   1 Hz", "   3 Hz", "  10 Hz", "  30 Hz", " 100 Hz", " 300   Hz", "   1 kHz", ... "   1   MHz"]

class SRS570(PVGroup):
    filter_type = pvproperty(name="filter_type.VAL", record="mbbo", value="NONE", enum_strings=["NONE", "HIPASS", "LOWPASS", "BAND"])
    filter_reset = pvproperty(name="filter_reset.VAL", value=0)
    low_freq = Cpt(EpicsSignal, "low_freq.VAL", kind="config", string=True)
    high_freq = Cpt(EpicsSignal, "high_freq.VAL", kind="config", string=True)
    gain_mode = pvproperty(name="gain_mode.VAL", record="mbbo", value="LOW NOISE", enum_strings=["LOW NOISE", "HIGH BW", "LOW DRIFT"])
    send_all = Cpt(EpicsSignal, "init.PROC", kind="omitted")
    reset = Cpt(EpicsSignal, "reset.PROC", kind="omitted")
    gain_num = pvproperty(name="sens_num.VAL", record="mbbo", value="1", enum_strings=["1", "2", "5", "10", "20", "100", "200", "500"])
    gain_unit = pvproperty(name="sens_unit.VAL", record="mbbo", value="pA/V", enum_strings=["pA/V", "nA/V", "uA/V", "mA/V"])
    invert = Cpt(EpicsSignal, "invert_on.VAL", kind="config", string=True)
