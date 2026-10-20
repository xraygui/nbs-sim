from .motors import FakeMotor, FakeFMBOMotor
from caproto.server import PVGroup, SubGroup
from nbs_bl.geometry.frames import make_regular_polygon
from nbs_bl.geometry.linalg import vec
import numpy as np
from os.path import isabs, join


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

    def __init__(self, prefix, parent=None, sample_file=None, **kwargs):
        super().__init__(prefix, parent=parent)
        self.sample_file = sample_file
        self.sample_map = None

    def load_sample_map(self, basedir=""):
        """Load ``sample_file`` (relative paths are taken from ``basedir``)."""
        if self.sample_file is None:
            return
        from ..samples import SampleMap

        path = self.sample_file
        if not isabs(path):
            path = join(basedir, path)
        print(f"Loading sample map {path}")
        self.sample_map = SampleMap(path)

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
