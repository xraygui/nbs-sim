import numpy as np
from scipy.interpolate import UnivariateSpline

from nbs_sim.devices.slits import ExitSlit
from nbs_sim.samples import gaussian_average


def make_slit(gap):
    slit = ExitSlit("TEST:eslit:", dispersion=0.002, ref_energy=285.0, floor=0.02, saturation_gap=200.0)
    slit.gap = lambda: gap
    return slit


def test_resolution_scales_with_gap_and_energy_squared():
    assert np.isclose(make_slit(50).resolution(285.0), np.hypot(0.1, 0.02))
    assert np.isclose(make_slit(100).resolution(285.0), np.hypot(0.2, 0.02))
    assert np.isclose(make_slit(50).resolution(570.0), np.hypot(0.4, 0.02))
    assert np.isclose(make_slit(0).resolution(285.0), 0.02)


def test_transmission_saturates():
    assert make_slit(100)._transmission() == 0.5
    assert make_slit(400)._transmission() == 1.0


def test_gaussian_average_broadens_a_peak():
    x = np.linspace(280, 290, 2001)
    peak = UnivariateSpline(x, np.exp(-0.5 * ((x - 285) / 0.05) ** 2), s=0, ext=3)
    sharp = gaussian_average(peak, 285.0, 0.0)
    broad = gaussian_average(peak, 285.0, 0.5)
    assert np.isclose(sharp, 1.0, atol=1e-3)
    # A 0.5 eV FWHM Gaussian on a 0.118 eV FWHM peak keeps about a fifth of its height
    assert 0.15 < broad < 0.3
