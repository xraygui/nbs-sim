import numpy as np
from caproto.server import PVGroup, SubGroup, pvproperty
from caproto import ChannelType
from .detectors import DetectorKindMixin

low_freq_strings = [
    "  0.03 Hz",
    "  0.1 Hz",
    "  0.3 Hz",
    "  1   Hz",
    "  3   Hz",
    " 10   Hz",
    " 30   Hz",
    "100   Hz",
    "300   Hz",
    "  1   kHz",
    "  3   kHz",
    " 10   kHz",
    " 30   kHz",
    "100   kHz",
    "300   kHz",
    "  1   MHz",
]

high_freq_strings = [
    "  0.03 Hz",
    "  0.1 Hz",
    "  0.3 Hz",
    "  1   Hz",
    "  3   Hz",
    " 10   Hz",
    " 30   Hz",
    "100   Hz",
    "300   Hz",
    "  1   kHz",
    "  3   kHz",
    " 10   kHz",
]


class SRS570Amplifier(PVGroup):
    """
    SRS570 lock-in amplifier detector with gain and filter simulation.

    This detector simulates the SRS570 lock-in amplifier with proper
    gain settings and filter functionality.
    """

    # Amplifier settings (srs_prefix)
    filter_type = pvproperty(
        name="filter_type",  # .VAL
        record="mbbo",
        value=0,
        enum_strings=[
            "   No filter",
            " 6 dB highpass",
            "12 dB highpass",
            " 6 dB bandpass",
            " 6 dB lowpass",
            "12 dB lowpass",
        ],
        dtype=ChannelType.ENUM,
    )
    filter_reset = pvproperty(name="filter_reset.VAL", value=0)
    low_freq = pvproperty(
        name="low_freq",  # .VAL
        record="mbbo",
        value=0,
        enum_strings=low_freq_strings,
        dtype=ChannelType.ENUM,
    )
    high_freq = pvproperty(
        name="high_freq",  # .VAL
        record="mbbo",
        value=0,
        enum_strings=high_freq_strings,
        dtype=ChannelType.ENUM,
    )
    gain_mode = pvproperty(
        name="gain_mode",  # .VAL
        record="mbbo",
        value="LOW NOISE",
        enum_strings=["LOW NOISE", "HIGH BW", "LOW DRIFT"],
        dtype=ChannelType.ENUM,
    )
    send_all = pvproperty(name="init.PROC", value=0)
    reset = pvproperty(name="reset.PROC", value=0)
    gain_num = pvproperty(
        name="sens_num",  # .VAL
        record="mbbo",
        value="1",
        enum_strings=["1", "2", "5", "10", "20", "100", "200", "500"],
        dtype=ChannelType.ENUM,
    )
    gain_unit = pvproperty(
        name="sens_unit",  # .VAL
        record="mbbo",
        value="pA/V",
        enum_strings=["pA/V", "nA/V", "uA/V", "mA/V"],
        dtype=ChannelType.ENUM,
    )
    invert = pvproperty(
        name="invert_on",  # .VAL
        record="mbbo",
        value="OFF",
        enum_strings=["OFF", "ON"],
        dtype=ChannelType.ENUM,
    )


def SRSADCFactory(prefix, *args, srs_prefix=None, **kwargs):
    """
    Factory function to create SRS570 detector with separate prefixes.

    Parameters
    ----------
    prefix : str
        Prefix for the ADC reading
    srs_prefix : str, optional
        Prefix for the SRS570 amplifier PVs, by default None (uses prefix)
    *args, **kwargs
        Additional arguments passed to the detector

    Returns
    -------
    SRS570
        Configured SRS570 detector
    """

    class SRS570(DetectorKindMixin, PVGroup):
        value = pvproperty(
            name=f"{prefix}Volt",
            value=0,
            dtype=float,
            read_only=True,
            doc="Intensity Value",
        )
        srs570 = SubGroup(SRS570Amplifier, prefix=srs_prefix)

        def __init__(self, prefix, kind="sc", signal_level=1e-9, parent=None, **kwargs):
            """
            Initialize the SRS570 detector.

            Parameters
            ----------
            prefix : str
                PV prefix for the ADC reading
            kind : str, optional
                Detector kind (i0, sc, ref, i1), by default "sc"
            srs_prefix : str, optional
                PV prefix for amplifier settings, by default None (uses prefix)
            parent : object, optional
                Parent beamline object, by default None
            """
            # If srs_prefix is provided, we need to handle the different prefixes
            # For now, we'll use the same prefix for both
            super().__init__(prefix, parent=parent)
            self.kind = kind
            self.signal_level = signal_level

        @value.scan(period=0.5)
        async def value(self, instance, async_lib):
            value = await self._read()
            await instance.write(value=value)

        async def _read(self):
            """
            Read the current value based on detector kind and gain settings.

            Returns
            -------
            float
                Current value in Amperes
            """
            # Get base intensity from parent beamline
            if self.kind == "i0":
                intensity = self.parent.intensity_func()
            elif self.kind == "sc":
                energy = self.parent.energy.value
                overlap = self.parent.distance_func(transmission=False)
                intensity = self.parent.intensity_func() * self.parent.yspl(energy)
                intensity = intensity * overlap
            elif self.kind == "ref":
                energy = self.parent.energy.value
                intensity = self.parent.intensity_func() * self.parent.refspl(energy)
            elif self.kind == "i1":
                overlap = self.parent.distance_func(transmission=True)
                intensity = self.parent.intensity_func()
                intensity = intensity * overlap
            else:
                intensity = self.parent.intensity_func()

            noise = np.random.normal(0, intensity * 0.01)  # 1% noise on signal
            intensity += noise
            # Apply gain settings
            gain_num = float(self.srs570.gain_num.value)
            gain_unit = self.srs570.gain_unit.value

            # Convert gain unit to scaling factor
            unit_scaling = {"pA/V": 1e-12, "nA/V": 1e-9, "uA/V": 1e-6, "mA/V": 1e-3}

            amplification = 1 / (
                gain_num * unit_scaling.get(gain_unit, 1e-9)
            )  # Default to nA/V

            # Apply gain and scaling
            current = intensity * self.signal_level * amplification

            # Add some realistic noise
            noise = np.random.normal(0, 0.01)  # 0.01 V noise floor
            current += noise

            # Apply inversion if enabled
            if self.srs570.invert.value == "ON":
                current = -current

            return current

    return SRS570("", *args, **kwargs)
