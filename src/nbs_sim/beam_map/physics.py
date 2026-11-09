"""
Flux, energy and bandwidth at every node of a beamline map, from the physics
inputs of a sim overlay.

- **Transmission** is a node's own: 0 while the node blocks (by its status),
  otherwise its transmission input clipped to [0, 1], or 1 without one.
- **Flux** is the flux arriving at a node, before its own transmission: the
  source flux times the transmission of every node upstream. The source flux
  is 0 while the beam is off, and 1 without a flux input.
- **Energy** and **Bandwidth** at a node come from the nearest node, itself
  or upstream, that sets them. Where none does, energy is NaN and bandwidth
  0.

A disconnected input fails safe outside sim mode, as for the status: the
transmission is 0 and the flux 0. In sim mode a disconnected transmission is
ignored (1), but a disconnected source flux is still 0, since there is
nothing to ignore it in favour of. A disconnected energy or bandwidth is NaN
in either mode.
"""

import math
from dataclasses import dataclass

from .status import beam_off_reason

NAN = float("nan")


@dataclass(frozen=True)
class NodePhysics:
    transmission: float
    flux: float
    energy: float
    bandwidth: float


def same(a, b):
    """Equal, counting NaN as equal to NaN."""
    return a == b or (math.isnan(a) and math.isnan(b))


def _transmission(name, bmap, status, values, sim):
    if status[name].blocking:
        return 0.0
    inp = bmap.physics.transmission.get(name)
    if inp is None:
        return 1.0
    x = inp.read(values)
    if x is None:
        return 1.0 if sim else 0.0
    return min(max(x, 0.0), 1.0)


def _nearest(table, path, values, unset):
    """The value from the first node on ``path`` that sets one."""
    for n in path:
        if n in table:
            x = table[n].read(values)
            return NAN if x is None else x
    return unset


def compute_physics(bmap, status, values, sim=False):
    """
    Return a dict of node name to NodePhysics, and the source flux.

    ``status`` is the map's ``compute_status`` result for the same values.
    """
    physics = bmap.physics
    if beam_off_reason(bmap, values, sim) is not None:
        source = 0.0
    elif physics.flux is None:
        source = 1.0
    else:
        x = physics.flux.read(values)
        source = 0.0 if x is None else max(x, 0.0)
    own = {
        name: _transmission(name, bmap, status, values, sim) for name in bmap.nodes
    }
    out = {}
    for name in bmap.nodes:
        upstream = bmap.ancestors(name)
        flux = source
        for n in upstream:
            flux *= own[n]
        path = [name] + upstream
        out[name] = NodePhysics(
            transmission=own[name],
            flux=flux,
            energy=_nearest(physics.energy, path, values, NAN),
            bandwidth=_nearest(physics.bandwidth, path, values, 0.0),
        )
    return out, source
