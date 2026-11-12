"""
Beam inputs for sim devices.

A sim device learns about the beam through a *beam source*, an object with
three methods:

- ``flux()``: the flux arriving at the device, in the map's relative units.
- ``energy()``: the photon energy at the device, eV.
- ``bandwidth(energy)``: the energy FWHM at the device, eV.

``beam_for(device)`` picks the source for a device:

- **BeamInput** reads the beam map IOC's physics PVs at the device's node
  over Channel Access (``{map_prefix}{node}:Flux`` and so on), so it works
  the same in the main nbs-sim process or in another container. Anything it
  has not received, or that the map leaves unset (NaN), comes from its
  fallback.
- **ParentBeam** computes the beam from the nbs-sim ``Beamline`` as before
  the beam map existed: ring current times shutter, aperture and gate valve
  transmissions, the energy device, and the slits' resolution.
- **FixedBeam** gives constant values, for a device with neither.

Devices that attenuate the beam serve their transmission (0 to 1) on a
``transmission`` PV, which a sim overlay of the beam map points at.

The sample model is shared through a file, not Python objects: the sim
manipulator serves ``{prefix}Sim:SampleID`` and ``{prefix}Sim:Overlap``, a
device anywhere watches them with ``SampleInput``, and reads per-sample data
from the sample file (the manipulator's ``sample_file``) with
``SampleTable``.
"""

import asyncio
import bisect
import csv
import logging
import math
import time
from os.path import dirname, isabs, join

from caproto import ChannelType

log = logging.getLogger(__name__)

FIELDS = ("Flux", "Energy", "Bandwidth")
# How long BeamInput keeps flux history for mean_flux, seconds.
HISTORY = 600.0


class FixedBeam:
    """A beam source with constant values."""

    def __init__(self, flux=1.0, energy=500.0, bandwidth=0.0):
        self._flux = flux
        self._energy = energy
        self._bandwidth = bandwidth

    def flux(self):
        return self._flux

    def energy(self):
        return self._energy

    def bandwidth(self, energy=None):
        return self._bandwidth


class ParentBeam:
    """The beam as the nbs-sim ``Beamline`` computes it."""

    def __init__(self, beamline):
        self.beamline = beamline

    def flux(self):
        return self.beamline.intensity_func()

    def energy(self):
        return self.beamline.energy.value

    def bandwidth(self, energy=None):
        if energy is None:
            energy = self.energy()
        return self.beamline.energy_resolution(energy)


_contexts = {}


def _context():
    """One caproto client context per event loop, shared by all inputs."""
    from caproto.asyncio.client import Context

    loop = asyncio.get_running_loop()
    if loop not in _contexts:
        _contexts[loop] = Context()
    return _contexts[loop]


class BeamInput:
    """
    The beam at one node of the beam map, from the map IOC's physics PVs.

    Parameters
    ----------
    map_prefix : str
        The map IOC's PV prefix, e.g. ``"NBS_MAP:"``.
    node : str
        The device's node in the map.
    fallback : beam source, optional
        Used for any value not (yet) received from the map. Defaults to a
        FixedBeam.

    The subscriptions start on the first ``start()``, which needs a running
    event loop; ``beam_for`` devices call it from their scan methods.
    """

    def __init__(self, map_prefix, node, fallback=None):
        self.map_prefix = map_prefix
        self.node = node
        self.fallback = fallback if fallback is not None else FixedBeam()
        self.values = {field: None for field in FIELDS}
        self._task = None
        self._using_fallback = None
        self._times = []
        self._fluxes = []

    def pvname(self, field):
        return f"{self.map_prefix}{self.node}:{field}"

    def start(self):
        """Start the subscriptions, once; a no-op after that."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._monitor())

    async def _monitor(self):
        names = {self.pvname(f): f for f in FIELDS}
        ctx = _context()
        async for event, context, data in ctx.monitor(
            *names, data_type=ChannelType.DOUBLE
        ):
            if event == "connection":
                if data != "connected":
                    self.values[names[context.name]] = None
                    self._note_fallback()
                continue
            try:
                value = float(data.data[0])
            except (IndexError, TypeError, ValueError):
                value = None
            field = names[context.pv.name]
            self.values[field] = value
            if field == "Flux" and value is not None:
                self._record(value)
            self._note_fallback()

    def _note_fallback(self):
        missing = self.values["Flux"] is None
        if missing != self._using_fallback:
            self._using_fallback = missing
            if missing:
                log.warning("%s: no flux from the beam map, using the fallback",
                            self.pvname("Flux"))
            else:
                log.info("%s: flux from the beam map", self.pvname("Flux"))

    @property
    def connected(self):
        """Whether the flux comes from the beam map."""
        return self.values["Flux"] is not None

    def _get(self, field):
        x = self.values[field]
        if x is None or math.isnan(x):
            return None
        return x

    def flux(self):
        x = self._get("Flux")
        return self.fallback.flux() if x is None else x

    def energy(self):
        x = self._get("Energy")
        return self.fallback.energy() if x is None else x

    def bandwidth(self, energy=None):
        x = self._get("Bandwidth")
        if x is None:
            return self.fallback.bandwidth(energy)
        return x

    def _record(self, flux, t=None):
        t = time.monotonic() if t is None else t
        self._times.append(t)
        self._fluxes.append(flux)
        cut = bisect.bisect_left(self._times, t - HISTORY)
        if cut > 1:
            del self._times[: cut - 1]
            del self._fluxes[: cut - 1]

    def mean_flux(self, t0, t1=None):
        """
        Time-averaged flux between monotonic times ``t0`` and ``t1`` (now by
        default), so an exposure sees a shutter that closed part way through.
        Uses the current flux when there is no history for the interval.
        """
        t1 = time.monotonic() if t1 is None else t1
        # Copies, since a device may call this from a worker thread while
        # _record runs on the event loop.
        times, fluxes = list(self._times), list(self._fluxes)
        if t1 <= t0 or not times or times[0] > t0 or len(times) != len(fluxes):
            return self.flux()
        total = 0.0
        # Flux holds each value until the next update.
        i = bisect.bisect_right(times, t0) - 1
        t = t0
        while t < t1:
            nxt = times[i + 1] if i + 1 < len(times) else t1
            end = min(nxt, t1)
            total += fluxes[i] * (end - t)
            t = end
            i += 1
        return total / (t1 - t0)


def beam_for(device):
    """
    The beam source for ``device``, made once and cached on it.

    A device with a ``beam_node`` and a parent beamline that names a beam map
    gets a BeamInput at that node, falling back to the parent beamline. A
    device with only a parent gets a ParentBeam, and a device with neither a
    FixedBeam. In an extra sim process (``nbs-sim --process``) the parent
    holds only some devices, so FixedBeam is the fallback there.
    """
    beam = getattr(device, "_beam_source", None)
    if beam is not None:
        return beam
    parent = getattr(device, "parent", None)
    node = getattr(device, "beam_node", None)
    map_prefix = getattr(parent, "beam_map_prefix", None)
    if (
        parent is not None
        and hasattr(parent, "intensity_func")
        and getattr(parent, "computes_beam", True)
    ):
        fallback = ParentBeam(parent)
    else:
        fallback = FixedBeam()
    if node and map_prefix:
        beam = BeamInput(map_prefix, node, fallback=fallback)
    else:
        beam = fallback
    device._beam_source = beam
    return beam


def start_beam(device):
    """``beam_for(device)``, with its subscriptions started if it has any.
    Call from a coroutine."""
    beam = beam_for(device)
    if isinstance(beam, BeamInput):
        try:
            beam.start()
        except RuntimeError:  # no running loop: use the fallback for now
            pass
    return beam


class SampleInput:
    """
    The sample in the beam, from a sim manipulator's ``Sim:SampleID`` and
    ``Sim:Overlap`` PVs under ``prefix``.

    ``sample_id`` is None with no sample in the beam, and ``overlap`` (the
    fraction of the beam on the sample bar) is None until it arrives. Call
    ``start()`` from a coroutine, as for BeamInput.
    """

    def __init__(self, prefix):
        self.prefix = prefix
        self.sample_id = None
        self.overlap = None
        self._task = None

    def start(self):
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._monitor())

    async def _monitor(self):
        sample_pv = f"{self.prefix}Sim:SampleID"
        overlap_pv = f"{self.prefix}Sim:Overlap"
        async for event, context, data in _context().monitor(sample_pv, overlap_pv):
            if event == "connection":
                if data != "connected":
                    if context.name == sample_pv:
                        self.sample_id = None
                    else:
                        self.overlap = None
                continue
            value = data.data[0] if len(data.data) else None
            if context.pv.name == sample_pv:
                if isinstance(value, bytes):
                    value = value.decode()
                self.sample_id = value or None
            else:
                self.overlap = None if value is None else float(value)


class SampleTable:
    """
    Rows of a sample CSV (the sim manipulator's ``sample_file``) by
    ``sample_id``, for devices that keep their own per-sample columns in it,
    such as an ``xps`` column naming a line file.
    """

    def __init__(self, path):
        self.path = path
        with open(path, newline="") as f:
            rows = csv.DictReader(f, skipinitialspace=True)
            self.rows = {row["sample_id"]: row for row in rows}

    def get(self, sample_id, column):
        """The sample's value in ``column``, or None if missing or empty."""
        row = self.rows.get(sample_id)
        if row is None:
            return None
        return row.get(column) or None

    def path_for(self, sample_id, column):
        """A file named in ``column``, relative to the sample file."""
        value = self.get(sample_id, column)
        if value is None or isabs(value):
            return value
        return join(dirname(self.path), value)
