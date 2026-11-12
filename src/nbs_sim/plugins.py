"""
Sim classes from other packages, found through entry points.

Two entry point groups:

- ``nbs_sim.loaders``: a translation table from real class to sim class, the
  same thing sim_conf.toml ``[loaders]`` holds. The entry point names a dict,
  or a function that returns one, e.g. in haxpes's pyproject.toml::

      [project.entry-points."nbs_sim.loaders"]
      haxpes = "haxpes.sim:LOADERS"

  Tables from all installed packages are merged in entry point name order,
  and sim_conf.toml ``[loaders]`` overrides them.
- ``nbs_sim.devices``: short, stable names for sim classes, e.g.
  ``peak-analyzer = "haxpes.sim.peak:PeakAnalyzerSim"``. A ``_target`` or
  loader table value may use the short name instead of a dotted path.

Sim code registered this way should import only caproto, numpy and
``nbs_sim.sdk``, never ophyd or bluesky, so the sim process stays light.
"""

import logging
from importlib.metadata import entry_points

from nbs_core.autoload import simpleResolver

log = logging.getLogger(__name__)

LOADERS = "nbs_sim.loaders"
DEVICES = "nbs_sim.devices"


def _group(name):
    return sorted(entry_points(group=name), key=lambda ep: ep.name)


def loader_table():
    """The merged ``nbs_sim.loaders`` tables of installed packages."""
    table = {}
    for ep in _group(LOADERS):
        try:
            loaders = ep.load()
            if callable(loaders):
                loaders = loaders()
        except Exception:
            log.exception("Could not load sim loaders %s (%s)", ep.name, ep.value)
            continue
        for key, target in loaders.items():
            if key in table and table[key] != target:
                log.warning(
                    "Sim loader for %s: %s (from %s) replaces %s",
                    key, target, ep.name, table[key],
                )
            table[key] = target
    return table


def device_names():
    """``nbs_sim.devices`` short names, mapped to their entry points."""
    return {ep.name: ep for ep in _group(DEVICES)}


def resolve(target):
    """The sim class for a ``_target``: a short name or a dotted path."""
    ep = device_names().get(target)
    if ep is not None:
        return ep.load()
    return simpleResolver(target)
