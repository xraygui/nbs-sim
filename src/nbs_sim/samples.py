"""Per-sample spectra for the simulated manipulator.

A sample map is a sample CSV in the format nbs-bl's ``Standard4SidedBar``
reads (``sample_id, sample_name, side, x1, y1, x2, y2, thickness, ...``) with
an extra ``spectrum`` column naming a two-column ``energy,yield`` CSV, relative
to the sample file, and optional columns:

- ``signal_scale`` (default 1) multiplies the sample's yield.
- ``noise`` (default 1) multiplies the relative counting noise of the
  sample's signal without changing its mean, so a noisy sample looks normal
  in intensity but needs repeat scans to average down.
- ``charging`` (default 0, off) scales an additive charging baseline (see
  ``ChargingModel``). The baseline is in absolute yield units and is not
  multiplied by ``signal_scale``, so it hurts weak samples most.
 It is the sim's ground truth: positions may
differ from the sample file the beamline loads, to model a misplaced sample.
"""

import time
from os.path import dirname, isabs, join

import numpy as np
from scipy.interpolate import UnivariateSpline
from scipy.special import erf
from nbs_bl.geometry.affine import Frame, find_rotation
from nbs_bl.geometry.bars import Standard4SidedBar


# Gaussian quadrature nodes over +-3 sigma for gaussian_average
_NODES = np.linspace(-3.0, 3.0, 25)
_WEIGHTS = np.exp(-0.5 * _NODES**2)
_WEIGHTS /= _WEIGHTS.sum()


def norm_erf(x, width=1):
    """Smooth step from 0 to 1 across x = 0: the fraction of a beam of
    ``width`` that a sample edge at distance ``x`` intercepts."""
    return 0.5 * (erf(2.0 * x / width) + 1)


def gaussian_average(func, energy, fwhm):
    """``func`` at ``energy``, convolved with a Gaussian of FWHM ``fwhm`` (eV)."""
    if not fwhm or fwhm <= 0:
        return float(func(energy))
    sigma = fwhm / 2.3548
    return float(np.dot(_WEIGHTS, func(energy + sigma * _NODES)))


class ChargingModel:
    """Charging baseline for samples with a ``charging`` strength.

    A spot is a ``spot_size`` mm cell of the sample surface. Each spot keeps
    its own exposure history, so the model is lazy: a spot's state is only
    updated when it is in the beam.

    The baseline (yield units, added to the sample's yield) is::

        charging * (first_amplitude * exp(-dose / first_tau)
                    + repeat_amplitude * exp(-t_on / repeat_tau))

    ``dose`` is the spot's accumulated beam time (s). It recovers toward 0
    with ``recover_tau`` while the spot is out of the beam, so the large
    first-exposure transient only comes back after a long rest. ``t_on`` is
    the time since the spot's current exposure began: it restarts whenever
    the spot has been out of the beam for more than ``gap`` seconds, or the
    energy drops by more than ``energy_reset`` eV (the start of a new scan
    with the shutter left open), so each re-scan starts with a smaller
    transient. Both decay with beam time, and
    a scan runs low to high in energy, so in a spectrum the baseline looks
    like a decay across the scan.

    Parameters are seconds of beam time; amplitudes are in the units of the
    sample spectra (a pre-edge yield of about 1).
    """

    def __init__(
        self,
        first_amplitude=2.0,
        first_tau=120.0,
        repeat_amplitude=0.5,
        repeat_tau=40.0,
        recover_tau=3600.0,
        gap=10.0,
        energy_reset=5.0,
        spot_size=1.0,
        clock=time.monotonic,
    ):
        self.first_amplitude = float(first_amplitude)
        self.first_tau = float(first_tau)
        self.repeat_amplitude = float(repeat_amplitude)
        self.repeat_tau = float(repeat_tau)
        self.recover_tau = float(recover_tau)
        self.gap = float(gap)
        self.energy_reset = float(energy_reset)
        self.spot_size = float(spot_size)
        self.clock = clock
        self.spots = {}

    def spot_key(self, sample_id, sx, sy):
        return (sample_id, int(np.floor(sx / self.spot_size)), int(np.floor(sy / self.spot_size)))

    def expose(self, key, beam_on=True, energy=None):
        """Advance the spot ``key`` to now and return its unit baseline
        (before the sample's ``charging`` strength)."""
        now = self.clock()
        state = self.spots.setdefault(
            key, {"dose": 0.0, "t_on": 0.0, "last": None, "energy": None}
        )
        if beam_on:
            if state["last"] is None:
                pass
            else:
                elapsed = now - state["last"]
                if elapsed > self.gap:
                    # The spot was out of the beam: partial recovery, new exposure
                    state["dose"] *= np.exp(-elapsed / self.recover_tau)
                    state["t_on"] = 0.0
                else:
                    state["dose"] += elapsed
                    state["t_on"] += elapsed
            last_energy = state["energy"]
            if (
                energy is not None
                and last_energy is not None
                and last_energy - energy > self.energy_reset
            ):
                state["t_on"] = 0.0
            state["last"] = now
            if energy is not None:
                state["energy"] = energy
        return self.first_amplitude * np.exp(
            -state["dose"] / self.first_tau
        ) + self.repeat_amplitude * np.exp(-state["t_on"] / self.repeat_tau)


class SampleMap:
    """Find which sample on a 4-sided bar is in the beam.

    The geometry matches ``nbs_bl.sim.manipulator.ManipulatorBuilder``: a bar
    attached at ``attachment_point``, beam along -y, rotation about z.

    Parameters
    ----------
    sample_file : str
        Sample CSV with a ``spectrum`` column.
    width, length : float
        Bar dimensions in mm.
    attachment_point : tuple
        Motor (x, y, z) that puts the bar attachment point in the beam.
    depth_tolerance : float
        How far (mm) the beam point may sit off the sample surface along its
        normal and still count as on the sample, i.e. a sample thickness.
        While a sample counts as hit, sc reads its yield whether or not the
        beam overlaps the bar, so a large value makes edges near samples
        appear early.
    misalignment : dict, optional
        Bar misalignment, as for ``devices.manipulator.bar_misalignment``.
    charging : dict, optional
        Parameters for ``ChargingModel``. Only samples with a nonzero
        ``charging`` column use it.
    """

    def __init__(
        self,
        sample_file,
        width=24.5,
        length=215,
        attachment_point=(0, 0, 464),
        depth_tolerance=0.2,
        misalignment=None,
        charging=None,
    ):
        self.depth_tolerance = depth_tolerance
        self.charging = ChargingModel(**(charging or {}))
        self.to_ideal = None
        if misalignment:
            from .devices.manipulator import bar_misalignment

            _, self.to_ideal = bar_misalignment(misalignment, attachment_point[2])
        self.manip_frame = Frame(origin=np.zeros(3))
        attachment_frame = self.manip_frame.make_child_frame(origin=attachment_point)
        self.holder = Standard4SidedBar(width, length)
        self.holder.attach_manipulator(attachment_frame)

        basedir = dirname(sample_file)
        self.samples = {}
        for sample_id, sample in self.holder.read_sample_file(sample_file).items():
            position = sample["position"]
            x1, y1, x2, y2 = position["coordinates"]
            position["thickness"] = float(position.get("thickness", 0))
            frame = self.holder.make_sample_frame(position)
            grazing = find_rotation(frame, (1, 0, 0), self.manip_frame, (0, -1, 0), 2)
            spec_path = sample["spectrum"]
            if not isabs(spec_path):
                spec_path = join(basedir, spec_path)
            data = np.loadtxt(spec_path, delimiter=",", skiprows=1)
            self.samples[sample_id] = {
                "name": sample.get("name", sample_id),
                "frame": frame,
                "grazing": np.degrees(grazing),
                "half_width": abs(x2 - x1) / 2.0,
                "half_height": abs(y2 - y1) / 2.0,
                "spline": UnivariateSpline(data[:, 0], data[:, 1], s=0, ext=3),
                "signal_scale": float(sample.get("signal_scale", 1.0)),
                "noise": float(sample.get("noise", 1.0)),
                "charging": float(sample.get("charging", 0.0)),
            }

    def sample_at(self, x, y, z, r):
        """Return the id of the sample in the beam at motor position (x, y, z, r), or None."""
        hit = self.locate(x, y, z, r)
        return None if hit is None else hit[0]

    def locate(self, x, y, z, r):
        """Return (sample_id, sx, sy), the sample in the beam and the beam's
        position on it (mm from its centre), or None."""
        xp, yp, zp = self.manip_frame.rotate_in_plane(
            (x, y, z), -np.radians(r), ax1=0, ax2=1
        )
        if self.to_ideal is not None:
            xp, yp, zp = self.to_ideal((xp, yp, zp))
        best = None
        for sample_id, s in self.samples.items():
            sx, sy, sz = self.manip_frame.to_frame((xp, yp, zp), s["frame"])
            facing = 0 < (r - s["grazing"]) % 360 < 180
            if (
                facing
                and abs(sx) <= s["half_width"]
                and abs(sy) <= s["half_height"]
                and abs(sz) <= self.depth_tolerance
            ):
                if best is None or abs(sz) < best[1]:
                    best = (sample_id, abs(sz), sx, sy)
        return None if best is None else (best[0], best[2], best[3])

    def spectrum(self, sample_id, energy, fwhm=0.0):
        """
        Yield of ``sample_id`` at ``energy``.

        With ``fwhm`` > 0 (eV), the spectrum is convolved with a Gaussian of
        that width, as a finite monochromator resolution would.
        """
        s = self.samples[sample_id]
        return s["signal_scale"] * gaussian_average(s["spline"], energy, fwhm)

    def noise(self, sample_id):
        """Relative noise multiplier of ``sample_id`` (1 is normal)."""
        return self.samples[sample_id]["noise"]

    def charging_baseline(self, sample_id, sx, sy, beam_on=True, energy=None):
        """Charging baseline (yield units) of the spot at (sx, sy) on
        ``sample_id``, advancing the spot's exposure if ``beam_on``. 0 for
        samples without charging."""
        strength = self.samples[sample_id]["charging"]
        if not strength:
            return 0.0
        key = self.charging.spot_key(sample_id, sx, sy)
        return strength * self.charging.expose(key, beam_on, energy)
