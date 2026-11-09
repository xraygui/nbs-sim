import numpy as np
from caproto.server import PVGroup, pvproperty

from ..samples import gaussian_average
from ..sdk import start_beam


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
        period = 0.05

        def __init__(
            self, prefix, *, parent=None, noise="gaussian", count_rate=40.0, **kwargs
        ):
            """
            Parameters
            ----------
            noise : {"gaussian", "poisson"}
                "gaussian" adds fixed noise of ``sigma``. "poisson" treats the
                value as ``count_rate`` counts per second per unit of signal, so
                relative noise falls as 1/sqrt(signal * dwell).
            count_rate : float
                Counts per second per unit of signal for ``noise="poisson"``.
            """
            super().__init__(prefix, parent=parent)
            self.noise = noise
            self.count_rate = count_rate

        # Update faster than the shortest dwell nbs-bl scalars use (0.1 s);
        # at 0.5 s most short dwells saw no update and read NaN
        @value.scan(period=period)
        async def value(self, instance, async_lib):
            value = await self._read()
            await instance.write(value=self._add_noise(value))

        def _add_noise(self, value):
            if self.noise == "poisson":
                scale = self.count_rate * self.period
                return np.random.poisson(max(value, 0) * scale) / scale
            return np.random.normal(value, self.sigma)

        async def _read(self):
            """Override this method to define how intensity is calculated."""
            return 0.0

    return Intensity


class DetectorKindMixin:
    """Mixin that provides detector-specific intensity calculations.

    This mixin defines how different kinds of detectors calculate their
    intensity values based on their type (i0, sc, ref, i1). Flux, energy and
    bandwidth come from the device's beam source (``nbs_sim.sdk``); the
    sample and the reference spectra still come from the parent beamline.
    """

    def kind_signal(self):
        """The detector's signal for its kind, before noise. Call from a
        coroutine, so the beam subscriptions can start."""
        beam = start_beam(self)
        flux = beam.flux()
        if self.kind == "i0":
            return flux
        elif self.kind == "sc":
            energy = beam.energy()
            sample_yield = self.parent.sample_yield(energy, beam.bandwidth(energy))
            if sample_yield is not None:
                return flux * sample_yield
            overlap = self.parent.distance_func(transmission=False)
            return flux * self.parent.yspl(energy) * overlap
        elif self.kind == "ref":
            # The reference sits in the same beam, so it gets the same mono broadening
            energy = beam.energy()
            fwhm = beam.bandwidth(energy)
            return flux * gaussian_average(self.parent.refspl, energy, fwhm)
        elif self.kind == "i1":
            return flux * self.parent.distance_func(transmission=True)
        else:
            return flux

    async def _read(self):
        return self.kind_signal()


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
            super().__init__(prefix, parent=parent, **kwargs)
            self.kind = kind

    return Detector


ADCVoltage = make_detector_class("Volt")
GenericDetector = make_detector_class("")
