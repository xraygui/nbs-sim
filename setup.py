from setuptools import setup, find_packages

setup(
    author="Charles Titus",
    author_email="charles.titus@nist.gov",
    install_requires=["caproto", "asyncio", "scipy", "nbs-bl", "numpy", "nbs-core"],
    name="nbs-sim",
    packages=find_packages(),
    package_data={"nbs-sim": ["*.npz"]},
    entry_points={"console_scripts": ["nbs-sim = nbs_sim.beamline:main"]},
)
