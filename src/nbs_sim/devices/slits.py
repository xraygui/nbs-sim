from caproto.server import PVGroup, SubGroup, pvproperty
from .motors import FakeFMBOMotor, FakeMotor
import numpy as np


class BaseQuadSlits(PVGroup):
    """
    Base class for 4-blade slits simulation.

    This provides common functionality for calculating transmission
    based on blade positions.
    """

    transmission = pvproperty(
        value=0.0,
        dtype=float,
        read_only=True,
        doc="Total beam transmission through slits",
    )

    def __init__(self, prefix, *, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
        # Parameters for transmission calculation
        self.min_opening = 0.1  # mm, minimum opening for any transmission
        self.max_opening = 5.0  # mm, opening for maximum transmission

    def _calc_size(self, pos1, pos2):
        """Helper to calculate opening size from two blade positions"""
        return abs(pos1 - pos2)

    @transmission.scan(period=0.1)
    async def transmission(self, instance, async_lib):
        """Calculate total transmission through slits"""
        # Calculate current openings
        v_size = self._calc_size(
            self.top.motor.field_inst.user_readback_value.value,
            self.bottom.motor.field_inst.user_readback_value.value,
        )
        h_size = self._calc_size(
            self.outboard.motor.field_inst.user_readback_value.value,
            self.inboard.motor.field_inst.user_readback_value.value,
        )

        # Calculate transmission for each direction
        def calc_transmission(size):
            if size < self.min_opening:
                return 0.0
            elif size > self.max_opening:
                return 1.0
            else:
                # Linear ramp between min and max
                numerator = size - self.min_opening
                denominator = self.max_opening - self.min_opening
                return numerator / denominator

        v_trans = calc_transmission(v_size)
        h_trans = calc_transmission(h_size)

        # Total transmission is product of both directions
        total_trans = v_trans * h_trans
        await instance.write(value=total_trans)


class QuadSlits(BaseQuadSlits):
    """
    A simulation of SST 4-blade slits using standard FakeMotors.

    This simulates the following motors:
    - Top blade
    - Bottom blade
    - Inboard blade
    - Outboard blade
    """

    # The real (or physical) positioners
    top = SubGroup(FakeMotor, velocity=2, precision=3, prefix="T}Mtr")
    bottom = SubGroup(FakeMotor, velocity=2, precision=3, prefix="B}Mtr")
    inboard = SubGroup(FakeMotor, velocity=2, precision=3, prefix="I}Mtr")
    outboard = SubGroup(FakeMotor, velocity=2, precision=3, prefix="O}Mtr")


class FMBOQuadSlits(BaseQuadSlits):
    """
    A simulation of SST 4-blade slits using FMBO motors.

    This simulates the following motors:
    - Top blade
    - Bottom blade
    - Inboard blade
    - Outboard blade

    Uses FakeFMBOMotor which includes additional status signals.
    """

    # The real (or physical) positioners with FMBO interface
    top = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="T}Mtr")
    bottom = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="B}Mtr")
    inboard = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="I}Mtr")
    outboard = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="O}Mtr")


class Slit(FakeMotor):
    """A slit simulation device."""

    transmission = pvproperty(
        value=0,
        dtype=float,
        read_only=True,
        doc="Transmission through slit",
    )

    @transmission.scan(period=0.05)
    async def transmission(self, instance, async_lib):
        value = await self._read()
        await self.transmission.write(value=value)

    def __init__(
        self,
        *args,
        trans_min,
        trans_max,
        velocity=10,
        precision=3,
        user_limits,
        parent=None,
        **kwargs
    ):
        """
        trans_min: Minimum opening for slit to transmit beam
        trans_max: Opening where transmission is maximum
        """
        super().__init__(
            *args,
            velocity=velocity,
            precision=precision,
            user_limits=user_limits,
            parent=None
        )
        self.trans_min = trans_min
        self.trans_max = trans_max

    async def _read(self):
        rbv = self.motor.field_inst.user_readback_value.value
        if rbv < self.trans_min:
            return 0
        if rbv > self.trans_max:
            return 1
        else:
            return (rbv - self.trans_min) / (self.trans_max - self.trans_min)

def QuadSlitsLimitFactory(*args, limits=None, **kwargs):
    """Factory function to create a simulated QuadSlits PVGroup.

    Parameters
    ----------
    limits : dict, optional
        Dictionary of limits for pseudo motors. Format:
        {'vsize': (min, max), 'hsize': (min, max),
         'vcenter': (min, max), 'hcenter': (min, max)}

    Returns
    -------
    QuadSlitsSim
        PVGroup class configured with the specified limits
    """

    _limits = {
        "vsize": (-1, 20),
        "hsize": (-1, 20),
        "vcenter": (-10, 10),
        "hcenter": (-10, 10),
    }
    if limits is not None:
        _limits.update(limits)

    class QuadSlitsSim(BaseQuadSlits):
        """Simulated quad slits with real and pseudo motors.

        Real motors are top, bottom, inboard, outboard.
        Pseudo motors are vsize, vcenter, hsize, hcenter.
        """

        # Calculate real motor limits from pseudo limits
        # For vertical motors:
        # vcenter + vsize/2 = top
        # vcenter - vsize/2 = bottom
        # So top/bottom range is vcenter ± vsize/2
        v_range = (
            _limits["vcenter"][0] - _limits["vsize"][1] / 2,
            _limits["vcenter"][1] + _limits["vsize"][1] / 2,
        )

        # Similarly for horizontal motors
        h_range = (
            _limits["hcenter"][0] - _limits["hsize"][1] / 2,
            _limits["hcenter"][1] + _limits["hsize"][1] / 2,
        )

        # The real (or physical) positioners
        top = SubGroup(
            FakeMotor,
            velocity=2,
            precision=3,
            user_limits=v_range,
            prefix="T}Mtr",
        )
        bottom = SubGroup(
            FakeMotor,
            velocity=2,
            precision=3,
            user_limits=v_range,
            prefix="B}Mtr",
        )
        inboard = SubGroup(
            FakeMotor,
            velocity=2,
            precision=3,
            user_limits=h_range,
            prefix="I}Mtr",
        )
        outboard = SubGroup(
            FakeMotor,
            velocity=2,
            precision=3,
            user_limits=h_range,
            prefix="O}Mtr",
        )

    return QuadSlitsSim(*args, **kwargs)


class ExitSlit(FakeMotor):
    """
    Monochromator exit slit that sets both flux and energy resolution.

    The motor is the slit gap in µm. Transmission rises linearly with the gap
    up to ``saturation_gap`` (the source image size), then stays at 1. The
    energy resolution (FWHM, eV) of a grating mono grows with the gap and with
    the square of the photon energy::

        dE = sqrt((dispersion * gap * (E / ref_energy)**2)**2 + floor**2)

    ``dispersion`` is eV per µm of gap at ``ref_energy``. The beamline
    convolves sample spectra with a Gaussian of this width, and the current
    value is served on the ``Resolution`` PV.
    """

    transmission = pvproperty(
        value=0.0, dtype=float, read_only=True, doc="Transmission through the slit"
    )
    resolution_pv = pvproperty(
        value=0.0,
        dtype=float,
        read_only=True,
        name="Resolution",
        precision=4,
        units="eV",
        doc="Energy resolution (FWHM) at the current energy",
    )

    def __init__(
        self,
        *args,
        dispersion=0.002,
        ref_energy=285.0,
        floor=0.02,
        saturation_gap=200.0,
        velocity=50,
        precision=1,
        user_limits=(5, 500),
        value=50,
        parent=None,
        **kwargs,
    ):
        super().__init__(
            *args,
            velocity=velocity,
            precision=precision,
            user_limits=user_limits,
            value=value,
            parent=parent,
            **kwargs,
        )
        self.dispersion = dispersion
        self.ref_energy = ref_energy
        self.floor = floor
        self.saturation_gap = saturation_gap
        self._beamline = parent

    def gap(self):
        return max(self.motor.field_inst.user_readback_value.value, 0.0)

    def resolution(self, energy):
        """Energy resolution (FWHM, eV) at ``energy`` for the current gap."""
        width = self.dispersion * self.gap() * (energy / self.ref_energy) ** 2
        return float(np.hypot(width, self.floor))

    def _transmission(self):
        return min(self.gap() / self.saturation_gap, 1.0)

    @transmission.scan(period=0.1)
    async def transmission(self, instance, async_lib):
        await self.transmission.write(value=self._transmission())

    @resolution_pv.scan(period=0.2)
    async def resolution_pv(self, instance, async_lib):
        energy_dev = getattr(self._beamline, "energy", None) if self._beamline is not None else None
        energy = getattr(energy_dev, "value", None)
        if energy is None:
            energy = self.ref_energy
        await self.resolution_pv.write(value=self.resolution(float(energy)))
