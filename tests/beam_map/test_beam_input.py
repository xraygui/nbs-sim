"""BeamInput against a running map IOC."""

import asyncio
import time

from nbs_sim.sdk import BeamInput, FixedBeam


def test_beam_input_follows_the_map_ioc(procs, overlay_path):
    procs.start_inputs()
    procs.start_map_ioc("--sim", "--sim-overlay", overlay_path)

    async def run():
        beam = BeamInput("NBS_MAP:", "branch1", fallback=FixedBeam(flux=-1.0))
        beam.start()
        end = time.monotonic() + 20
        while beam.flux() != 400.0 and time.monotonic() < end:
            await asyncio.sleep(0.1)
        return beam.flux(), beam.energy(), beam.bandwidth()

    assert asyncio.run(run()) == (400.0, 500.0, 0.25)
