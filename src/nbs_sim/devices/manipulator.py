from .motors import FakeMotor, FakeFMBOMotor
from caproto.server import PVGroup, SubGroup
from nbs_bl.geometry.frames import make_regular_polygon
from nbs_bl.geometry.linalg import vec
import numpy as np
from os.path import isabs, join


def bar_misalignment(misalignment, attachment_z=464):
    """
    A rigid misalignment of the sample bar, as a pair of functions.

    Points are in nbs-bl manipulator coordinates: the motor (x, y, z) that
    puts the point in the beam at r = 0, with the bar hanging from the
    attachment point (0, 0, attachment_z) on the rotation axis.

    Parameters
    ----------
    misalignment : dict
        Any of ``x``, ``y`` (mm, shift of the whole bar off the rotation
        axis), ``angle`` (degrees, rotation of the bar about its own long
        axis, i.e. on its mount), ``tilt_x``, ``tilt_y`` (degrees, rotation
        about the x and y axes through the attachment point). Missing keys
        are 0.

    Returns
    -------
    forward, inverse : callable
        Map a point on the ideal bar to the true bar, and back.
    """
    m = {k: float(misalignment.get(k, 0)) for k in ("x", "y", "angle", "tilt_x", "tilt_y")}
    a, tx, ty = (np.radians(m[k]) for k in ("angle", "tilt_x", "tilt_y"))
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(tx), -np.sin(tx)], [0, np.sin(tx), np.cos(tx)]])
    ry = np.array([[np.cos(ty), 0, np.sin(ty)], [0, 1, 0], [-np.sin(ty), 0, np.cos(ty)]])
    rot = rx @ ry @ rz
    attach = np.array([0.0, 0.0, attachment_z])
    shift = np.array([m["x"], m["y"], 0.0])

    def forward(p):
        return attach + rot @ (np.asarray(p, dtype=float) - attach) + shift

    def inverse(q):
        return attach + rot.T @ (np.asarray(q, dtype=float) - shift - attach)

    return forward, inverse


class ManipulatorBase(PVGroup):
    """
    A fake 4-axis manipulator
    """

    geometry = make_regular_polygon(24.5, 215, 4)
    origin = vec(0, 0, 464, 0)

    def distance_to_beam(self):
        mp = (
            self.x.motor.field_inst.user_readback_value.value,
            self.y.motor.field_inst.user_readback_value.value,
            self.z.motor.field_inst.user_readback_value.value,
            self.r.motor.field_inst.user_readback_value.value,
        )
        beam_pos = tuple(x - ox for x, ox in zip(mp, self.origin))
        distances = [side.distance_to_beam(*beam_pos) for side in self.geometry]
        return np.min(distances)

    def motor_position(self):
        return tuple(
            m.motor.field_inst.user_readback_value.value
            for m in (self.x, self.y, self.z, self.r)
        )

    def __init__(
        self, prefix, parent=None, sample_file=None, misalignment=None, **kwargs
    ):
        super().__init__(prefix, parent=parent)
        self.sample_file = sample_file
        self.sample_map = None
        self.misalignment = misalignment
        if misalignment:
            self.geometry = self._misaligned_geometry(misalignment)

    def _misaligned_geometry(self, misalignment, width=24.5, length=215):
        """The bar from make_regular_polygon, moved by bar_misalignment."""
        az = self.origin[2]
        forward, _ = bar_misalignment(misalignment, az)
        # make_regular_polygon's first side, in its own coordinates (x and z
        # flipped from manipulator coordinates, z measured down from the
        # attachment point)
        p1 = vec(width / 2.0, width / 2.0, length)
        points = (p1, p1 + vec(0, 0, -1), p1 + vec(0, -1, 0))

        def to_manip(g):
            return np.array([-g[0], g[1], az - g[2]])

        def from_manip(c):
            return vec(-c[0], c[1], az - c[2])

        moved = tuple(from_manip(forward(to_manip(p))) for p in points)
        print(f"Misaligned sample bar: {misalignment}")
        return make_regular_polygon(width, length, 4, points=moved)

    def load_sample_map(self, basedir=""):
        """Load ``sample_file`` (relative paths are taken from ``basedir``)."""
        if self.sample_file is None:
            return
        from ..samples import SampleMap

        path = self.sample_file
        if not isabs(path):
            path = join(basedir, path)
        print(f"Loading sample map {path}")
        self.sample_map = SampleMap(path, misalignment=self.misalignment)

    def current_sample(self):
        """Id of the sample in the beam, or None if there is no map or no sample."""
        if self.sample_map is None:
            return None
        return self.sample_map.sample_at(*self.motor_position())


class Manipulator(ManipulatorBase):
    x = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampX}Mtr")
    y = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampY}Mtr")
    z = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampZ}Mtr")
    r = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampTh}Mtr")


class ManipulatorRSOXS(ManipulatorBase):
    x = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="X}Mtr")
    y = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="Y}Mtr")
    z = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="Z}Mtr")
    r = SubGroup(FakeFMBOMotor, velocity=2, precision=3, prefix="Yaw}Mtr")

class ManipulatorNEXAFS(ManipulatorBase):
    x = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampX}Mtr")
    y = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampY}Mtr")
    z = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampZ}Mtr")
    r = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampRot}Mtr")


class MultiMesh(PVGroup):
    """
    A fake 1-axis manipulator
    """

    x = SubGroup(FakeMotor, velocity=10.0, precision=3, prefix="MMesh}Mtr")

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
