"""
Beam status of every node in a beamline map.

``values`` maps each input PV name to its current value, or to None (or
leaves it out) when the PV is disconnected. Outside sim mode a disconnected
PV fails safe: a blocker blocks, a selection is not selected, and the beam
is off. In sim mode a disconnected PV is ignored, because simulations often
cover only part of the map.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeStatus:
    blocking: bool
    path_clear: bool
    beam_expected: bool
    reason: str


def _blocked(node, values, sim):
    """Return the reason this node blocks the beam, or None."""
    for cond in node.blocked_when:
        x = values.get(cond.pv)
        if x is None:
            if not sim:
                return f"{node.name}: {cond.pv} disconnected"
        elif cond.holds(x):
            return f"{node.name} blocked: {cond.text(x)}"
    for cond in node.selected_when:
        x = values.get(cond.pv)
        if x is None:
            if not sim:
                return f"{node.name}: {cond.pv} disconnected"
        elif not cond.holds(x):
            return f"{node.name} not selected: {cond.text(x)}"
    return None


def beam_off_reason(bmap, values, sim):
    """Return the reason the global beam is off, or None."""
    for cond in bmap.beam_on:
        x = values.get(cond.pv)
        if x is None:
            if not sim:
                return f"beam off: {cond.pv} disconnected"
        elif not cond.holds(x):
            return f"beam off: {cond.text(x)}"
    return None


def compute_status(bmap, values, sim=False):
    """Return a dict of node name to NodeStatus."""
    own = {name: _blocked(node, values, sim) for name, node in bmap.nodes.items()}
    beam_off = beam_off_reason(bmap, values, sim)
    status = {}
    for name in bmap.nodes:
        # The reason is the closest blocker on the path, this node included,
        # so downstream blockers stay visible while an upstream one is shut.
        blockers = [own[n] for n in [name] + bmap.ancestors(name) if own[n]]
        blocking = own[name] is not None
        path_clear = len(blockers) == (1 if blocking else 0)
        reason = blockers[0] if blockers else beam_off or ""
        status[name] = NodeStatus(
            blocking=blocking,
            path_clear=path_clear,
            beam_expected=path_clear and not blocking and beam_off is None,
            reason=reason,
        )
    return status
