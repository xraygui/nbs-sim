"""Per-sample spectra for the simulated manipulator.

A sample map is a sample CSV in the format nbs-bl's ``Standard4SidedBar``
reads (``sample_id, sample_name, side, x1, y1, x2, y2, thickness, ...``) with
an extra ``spectrum`` column naming a two-column ``energy,yield`` CSV, relative
to the sample file. The same file can be loaded on the control side with
``load_samples``.
"""

from os.path import dirname, isabs, join

import numpy as np
from scipy.interpolate import UnivariateSpline
from nbs_bl.geometry.affine import Frame, find_rotation
from nbs_bl.geometry.bars import Standard4SidedBar


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
        normal and still count as on the sample.
    """

    def __init__(
        self,
        sample_file,
        width=24.5,
        length=215,
        attachment_point=(0, 0, 464),
        depth_tolerance=5.0,
    ):
        self.depth_tolerance = depth_tolerance
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
            }

    def sample_at(self, x, y, z, r):
        """Return the id of the sample in the beam at motor position (x, y, z, r), or None."""
        xp, yp, zp = self.manip_frame.rotate_in_plane(
            (x, y, z), -np.radians(r), ax1=0, ax2=1
        )
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

    def spectrum(self, sample_id, energy):
        return float(self.samples[sample_id]["spline"](energy))
