import numpy as np

from nbs_sim.beamline import Beamline
from nbs_sim.samples import gaussian_average


def test_reference_has_its_edge_near_284_eV():
    ioc = Beamline(config={"devices": {}, "groups": {}, "roles": {}}, prefix="SIM:")
    x = np.arange(275, 300, 0.05)
    y = ioc.refspl(x)
    assert abs(x[np.argmax(np.gradient(y, x))] - 284.3) < 0.2


def test_broadening_lowers_the_peak():
    ioc = Beamline(config={"devices": {}, "groups": {}, "roles": {}}, prefix="SIM:")
    x = np.arange(280, 300, 0.05)
    peak = x[np.argmax(ioc.refspl(x))]
    sharp = gaussian_average(ioc.refspl, peak, 0)
    broad = gaussian_average(ioc.refspl, peak, 1.0)
    assert broad < sharp
