"""Per-sample spectra for the simulated manipulator.

A sample map is a sample CSV in the format nbs-bl's ``Standard4SidedBar``
reads (``sample_id, sample_name, side, x1, y1, x2, y2, thickness, ...``) with
an extra ``spectrum`` column naming a two-column ``energy,yield`` CSV, relative
to the sample file, and an optional ``signal_scale`` column (default 1) that
multiplies the sample's yield. It is the sim's ground truth: positions may
differ from the sample file the beamline loads, to model a misplaced sample.
"""

from os.path import dirname, isabs, join

import numpy as np
from scipy.interpolate import UnivariateSpline
from nbs_bl.geometry.affine import Frame, find_rotation
from nbs_bl.geometry.bars import Standard4SidedBar


# Gaussian quadrature nodes over +-3 sigma for gaussian_average
_NODES = np.linspace(-3.0, 3.0, 25)
_WEIGHTS = np.exp(-0.5 * _NODES**2)
_WEIGHTS /= _WEIGHTS.sum()


def gaussian_average(func, energy, fwhm):
    """``func`` at ``energy``, convolved with a Gaussian of FWHM ``fwhm`` (eV)."""
    if not fwhm or fwhm <= 0:
        return float(func(energy))
    sigma = fwhm / 2.3548
    return float(np.dot(_WEIGHTS, func(energy + sigma * _NODES)))


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
    """

    def __init__(
        self,
        sample_file,
        width=24.5,
        length=215,
        attachment_point=(0, 0, 464),
        depth_tolerance=0.2,
        misalignment=None,
    ):
        self.depth_tolerance = depth_tolerance
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
            }

    def sample_at(self, x, y, z, r):
        """Return the id of the sample in the beam at motor position (x, y, z, r), or None."""
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
                    best = (sample_id, abs(sz))
        return None if best is None else best[0]

    def spectrum(self, sample_id, energy, fwhm=0.0):
        """
        Yield of ``sample_id`` at ``energy``.

        With ``fwhm`` > 0 (eV), the spectrum is convolved with a Gaussian of
        that width, as a finite monochromator resolution would.
        """
        s = self.samples[sample_id]
        return s["signal_scale"] * gaussian_average(s["spline"], energy, fwhm)
