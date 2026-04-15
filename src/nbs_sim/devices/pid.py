from caproto.server import PVGroup, pvproperty


class PIDGroup(PVGroup):
    """PID Controller PV Group.

    Parameters
    ----------
    prefix : str
        The prefix for all PVs in this group
    """

    # Read-only status PVs
    lastinput = pvproperty(value=0.0, name="Inp-Sts.A", read_only=True)
    pid_out = pvproperty(value=0.0, name="PID.OVAL", read_only=True)
    mtr_out = pvproperty(value=0.0, name="Val:OBuf3.OVAL", read_only=True)

    # Configuration PVs
    setpoint = pvproperty(value=0.0, name="PID-SP")
    K_P = pvproperty(value=1.0, name="PID.KP")
    K_I = pvproperty(value=0.0, name="PID.KI")
    K_D = pvproperty(value=0.0, name="PID.KD")
    dband = pvproperty(value=0.0, name="Val:DBnd-SP")
    pidcontrol = pvproperty(value=0, name="Sts:FB-Sel")
    updaterate = pvproperty(value=1.0, name="Inp-Sts.SCAN")
    in_low = pvproperty(value=-1e6, name="Inp-LowLim")
    in_high = pvproperty(value=1e6, name="Inp-HighLim")
    out_low = pvproperty(value=-1e6, name="Out-LowLim")
    out_high = pvproperty(value=1e6, name="Out-HighLim")
    permitlatch = pvproperty(value=0, name="Perm-Ltch")

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
