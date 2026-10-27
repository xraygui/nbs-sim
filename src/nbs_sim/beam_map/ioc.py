"""
The beamline map IOC.

Reads a map file, monitors every PV named in its conditions, and serves four
read-only status PVs per node: ``{prefix}{node}:Blocking``, ``:PathClear``,
``:BeamExpected`` and ``:Reason``. It never writes to the PVs it monitors.

Run with ``nbs-map-ioc --map beam_map.toml``. ``--sim``, or ``NBS_SIM_MODE=1``
in the environment, ignores disconnected PVs instead of failing safe.

The PV database is built directly rather than from a PVGroup, because
pvproperty names are expanded as format strings and input PV names such as
``XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON`` would break that.
"""

import argparse
import logging
import os

from caproto import AccessRights, ChannelChar, ChannelEnum, ChannelString, ChannelType
from caproto.asyncio.client import Context
from caproto.server import run

from .mapfile import load_map
from .status import compute_status

log = logging.getLogger(__name__)

STATUSES = {
    "Blocking": "blocking",
    "PathClear": "path_clear",
    "BeamExpected": "beam_expected",
    "Reason": "reason",
}
REASON_MAX_LENGTH = 256


class _ReadOnly:
    def check_access(self, hostname, username):
        return AccessRights.READ


class ReadOnlyEnum(_ReadOnly, ChannelEnum):
    pass


class ReadOnlyChar(_ReadOnly, ChannelChar):
    pass


class ReadOnlyString(_ReadOnly, ChannelString):
    pass


class MapIOC:
    """Status PVs for a beam map, kept up to date from its input PVs."""

    def __init__(self, bmap, prefix=None, sim=False):
        self.bmap = bmap
        self.prefix = bmap.prefix if prefix is None else prefix
        self.sim = sim
        self.values = {pv: None for pv in bmap.input_pvs()}
        self.status = compute_status(bmap, self.values, sim)
        self.pvdb = {f"{self.prefix}MapName": ReadOnlyString(value=bmap.name)}
        self.channels = {}
        for node, status in self.status.items():
            for suffix, field in STATUSES.items():
                value = getattr(status, field)
                if suffix == "Reason":
                    # A char array, not reported as a string: a DBR_STRING
                    # would cut the reason at 40 characters.
                    channel = ReadOnlyChar(value=value, max_length=REASON_MAX_LENGTH)
                else:
                    channel = ReadOnlyEnum(
                        value="On" if value else "Off", enum_strings=["Off", "On"]
                    )
                self.channels[(node, field)] = channel
                self.pvdb[f"{self.prefix}{node}:{suffix}"] = channel

    async def update(self):
        """Recompute every node and write the status PVs that changed."""
        new = compute_status(self.bmap, self.values, self.sim)
        for node, status in new.items():
            for field in STATUSES.values():
                value = getattr(status, field)
                if value == getattr(self.status[node], field):
                    continue
                if isinstance(value, bool):
                    value = "On" if value else "Off"
                await self.channels[(node, field)].write(value)
        self.status = new

    async def monitor(self, async_lib):
        """Startup hook: subscribe to every input PV and track it."""
        if self.sim:
            for pv in sorted(self.values):
                log.info("Sim mode: %s is ignored while disconnected", pv)
        await self.update()
        if not self.values:
            return
        ctx = Context()
        async for event, context, data in ctx.monitor(
            *self.values, data_type=ChannelType.DOUBLE
        ):
            if event == "connection":
                name = context.name
                if data == "disconnected":
                    self.values[name] = None
                    log.warning("%s disconnected", name)
                else:
                    log.info("%s connected", name)
            else:
                self.values[context.pv.name] = float(data.data[0])
            await self.update()


def make_ioc(bmap, prefix=None, sim=False):
    return MapIOC(bmap, prefix=prefix, sim=sim)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Beamline map status IOC")
    parser.add_argument("--map", required=True, help="Path to the map file")
    parser.add_argument(
        "--prefix", default=None, help="Status PV prefix (default: from the map)"
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Ignore disconnected PVs (also on when NBS_SIM_MODE=1)",
    )
    parser.add_argument("--list-pvs", action="store_true", help="Log PV names")
    parser.add_argument("--interfaces", nargs="+", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    sim = args.sim or os.environ.get("NBS_SIM_MODE", "") == "1"
    ioc = make_ioc(load_map(args.map), prefix=args.prefix, sim=sim)
    run(
        ioc.pvdb,
        interfaces=args.interfaces,
        log_pv_names=args.list_pvs,
        startup_hook=ioc.monitor,
    )


if __name__ == "__main__":
    main()
