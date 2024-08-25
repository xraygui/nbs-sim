from caproto.ioc_examples.fake_motor_record import FakeMotor
from caproto.server import PVGroup, SubGroup
from nbs_bl.geometry.frames import make_regular_polygon
from nbs_bl.geometry.linalg import vec
import numpy as np


class Manipulator(PVGroup):
    """
    A fake 4-axis manipulator
    """

    x = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampX}}Mtr")
    y = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampY}}Mtr")
    z = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampZ}}Mtr")
    r = SubGroup(FakeMotor, velocity=2, precision=3, prefix="SampTh}}Mtr")

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

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)


class MultiMesh(PVGroup):
    """
    A fake 1-axis manipulator
    """

    x = SubGroup(FakeMotor, velocity=10.0, precision=3, prefix="MMesh}}Mtr")

    def __init__(self, prefix, parent=None, **kwargs):
        super().__init__(prefix, parent=parent)
