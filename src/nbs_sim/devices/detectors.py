import numpy as np
from caproto.server import PVGroup, pvproperty


def make_intensity_class(pv_name="Intensity"):
    """Create a base class for any device that reads intensity values.

    Parameters
    ----------
    pv_name : str
        Name of the PV that will hold the intensity value

    Returns
    -------
    class
        A PVGroup subclass with an intensity reading PV
    """

    class Intensity(PVGroup):
        value = pvproperty(
            name=pv_name, value=0, dtype=float, read_only=True, doc="Intensity Value"
        )
        sigma = 0.05

        def __init__(self, prefix, *, parent=None, **kwargs):
            super().__init__(prefix, parent=parent)

        @value.scan(period=0.5)
        async def value(self, instance, async_lib):
            value = await self._read()
            v = np.random.normal(value, self.sigma)
            await instance.write(value=v)

        async def _read(self):
            """Override this method to define how intensity is calculated."""
            return 0.0

    return Intensity


class DetectorKindMixin:
    """Mixin that provides detector-specific intensity calculations.

    This mixin defines how different kinds of detectors calculate their
    intensity values based on their type (i0, sc, ref, i1).
    """

    async def _read(self):
        if self.kind == "i0":
            intensity = self.parent.intensity_func()
            return intensity
        elif self.kind == "sc":
            energy = self.parent.energy.value
            overlap = self.parent.distance_func(transmission=False)
            intensity = self.parent.intensity_func() * self.parent.yspl(energy)
            return intensity * overlap
        elif self.kind == "ref":
            energy = self.parent.energy.value
            intensity = self.parent.intensity_func() * self.parent.refspl(energy)
            return intensity
        elif self.kind == "i1":
            overlap = self.parent.distance_func(transmission=True)
            intensity = self.parent.intensity_func()
            return intensity * overlap


def make_detector_class(pv_name="Intensity"):
    """Create a detector class with the DetectorKindMixin.

    Parameters
    ----------
    pv_name : str
        Name of the PV that will hold the intensity value

    Returns
    -------
    class
        A detector class that combines Intensity and DetectorKindMixin
    """

    class Detector(DetectorKindMixin, make_intensity_class(pv_name)):
        def __init__(self, prefix, kind="sc", parent=None, **kwargs):
            super().__init__(prefix, parent=parent)
            self.kind = kind

    return Detector


ADCVoltage = make_detector_class("Volt")
GenericDetector = make_detector_class("")
