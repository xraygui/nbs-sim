from caproto.server import (
    PVGroup,
    SubGroup,
    template_arg_parser,
    pvproperty,
    run,
    PvpropertyDouble,
)
import time
from .load import createIOCDevice
import numpy as np
from os.path import join, dirname, exists
from scipy.interpolate import UnivariateSpline
from nbs_core.beamline import BeamlineModel
from nbs_core.autoconf import generate_device_config, load_settings
from nbs_core.autoload import loadFromConfig
from .beam_map.mapfile import default_overlay, load_map
from .plugins import loader_table
from .samples import norm_erf

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


class Beamline(BeamlineModel, PVGroup):
    # Stand-in for the facility's beam-available signal, so the beamline map
    # IOC has a global beam condition. Write 0 to simulate a beam dump.
    beam_available = pvproperty(value=1, dtype=int, name="beam_available")

    def __init__(
        self, *args, config, config_dir="", beam_map=None, process=None, **kwargs
    ):
        """
        ``beam_map`` is a BeamMap whose IOC serves physics PVs. Devices with
        a ``_node`` then read their beam from it (see ``nbs_sim.sdk``).

        ``process`` names the extra sim process this is (``--process``), or
        None for the main one. Only the main process holds the whole
        beamline, so only it can compute the beam itself.
        """
        super().__init__(*args, devices={}, groups={}, roles={}, **kwargs)
        self.config_dir = config_dir
        self.process = process
        self.computes_beam = process is None
        self.beam_map = beam_map
        self.beam_map_prefix = beam_map.prefix if beam_map is not None else None
        self.load_detector_data()
        devices, groups, roles = loadFromConfig(config, createIOCDevice, parent=self)
        self.loadDevices(devices, groups, roles)
        self.transmission_list = []

        self.configure_beamline()
        self.check_nodes(devices)

    def check_nodes(self, devices):
        """Warn about devices placed on nodes the beam map lacks."""
        if self.beam_map is None:
            return
        for key, device in devices.items():
            node = getattr(device, "beam_node", None)
            if node and node not in self.beam_map.nodes:
                print(f"Warning: {key} is on node {node!r}, not in the beam map")

    def load_detector_data(self):
        dirpath = dirname(__file__)
        print(dirpath)
        data = np.load(join(dirpath, "all_edges.npz"))
        refdata = np.load(join(dirpath, "all_ref.npz"))
        self.yspl = UnivariateSpline(data["x"], data["y"], s=0, ext=3)
        self.refspl = UnivariateSpline(refdata["x"], refdata["y"], s=0, ext=3)

    def sample_manipulator(self):
        # Profiles give the manipulator the nbs-bl role "primary_sampleholder";
        # "primary_manipulator" is never set from config but kept for callers
        if self.primary_manipulator is not None:
            return self.primary_manipulator
        return getattr(self, "primary_sampleholder", None)

    def sample_yield(self, energy, fwhm=None):
        """Yield of the sample in the beam, or None if no sample map applies.
        ``fwhm`` is the energy resolution, by default the slits'."""
        manip = self.sample_manipulator()
        if manip is None or getattr(manip, "sample_map", None) is None:
            return None
        sample_id = manip.current_sample()
        if sample_id is None:
            return None
        if fwhm is None:
            fwhm = self.energy_resolution(energy)
        return manip.sample_map.spectrum(sample_id, energy, fwhm)

    def energy_resolution(self, energy):
        """Mono resolution (FWHM, eV) from the slits role, or 0 without one."""
        slit = getattr(self, "slits", None)
        if slit is None or not hasattr(slit, "resolution"):
            return 0.0
        return slit.resolution(energy)

    def add_to_transmission(self, device):
        self.transmission_list.append(device)

    def current_func(self):
        # A beam dump empties the ring, which also takes out every detector
        if self.beam_available.value == 0:
            return 0.0
        t = time.monotonic() % (300)
        if t < 270:
            current = 500 - 50 * t / 270
        else:
            current = 500 - 50 * (300 - t) / 30
        return current

    def intensity_func(self, position=-1):
        base = self.current_func()
        for trans_dev in self.transmission_list:
            base *= trans_dev.transmission.value
        return base

    def distance_func(self, transmission=False):
        manip = self.sample_manipulator()
        if manip is not None:
            dist = manip.distance_to_beam()
        else:
            dist = 0
        if transmission:
            sgn = 1
        else:
            sgn = -1
        intensity = norm_erf(sgn * dist, 1)
        return intensity

    def configure_beamline(self):
        self.configure_gatevalves()
        self.configure_shutters()
        self.configure_apertures()
        self.configure_detectors()
        self.configure_samples()

    def configure_samples(self):
        manip = self.sample_manipulator()
        if manip is not None and hasattr(manip, "load_sample_map"):
            manip.load_sample_map(self.config_dir)

    def configure_shutters(self):
        for key, device in self.shutters.items():
            print(f"Adding {key} to transmission")
            self.add_to_transmission(device)

    def configure_apertures(self):
        for key, device in self.apertures.items():
            print(f"Adding {key} to transmission")
            self.add_to_transmission(device)

    def configure_gatevalves(self):
        for key, device in self.gatevalves.items():
            print(f"Adding {key} to transmission")
            self.add_to_transmission(device)

    def configure_detectors(self):
        pass

    def configure_motors(self):
        pass


def sim_loaders(config_file):
    """Installed packages' loader tables, under sim_conf.toml [loaders]."""
    table = loader_table()
    table.update(load_settings(config_file, sim_mode=True).get("loaders", {}))
    return table


def select_process(config, process=None):
    """The devices that run in ``process`` (``_process`` in the config), or
    with ``process`` None, the devices that name no process."""
    return {k: v for k, v in config.items() if v.get("_process") == process}


def main(argv=None):
    parser, split_args = template_arg_parser(
        desc="Simulation IOC Generator", default_prefix="SIM:"
    )
    # Create a group for startup-dir that is not required and not mutually exclusive
    parser.add_argument(
        "--startup-dir",
        help="Directory to initialize the simulation. Either this or both --device-file and --config-file must be provided, but not both.",
    )

    # Add device-file and config-file directly to the parser, not in a mutually exclusive group
    parser.add_argument(
        "--device-file",
        required=False,
        help="Location of device file. Required if --startup-dir is not provided.",
    )
    parser.add_argument(
        "--beam-map",
        help="Beam map whose IOC serves physics PVs (default: the startup "
        "dir's beam_map.toml, if it has a beam_map.sim.toml overlay)",
    )
    parser.add_argument(
        "--no-beam-map",
        action="store_true",
        help="Compute the beam in this process even if there is a beam map",
    )
    parser.add_argument(
        "--process",
        help="Run only the devices with this _process, as an extra sim "
        "process; by default run the devices that name no process",
    )
    parser.add_argument(
        "--config-file",
        required=False,
        help="Location of simulation file. Required if --startup-dir is not provided.",
    )
    args = parser.parse_args()
    ioc_options, run_options = split_args(args)

    # Validate that either startup-dir or both device-file and config-file are provided
    if args.startup_dir:
        device_file = join(args.startup_dir, "devices.toml")
        config_file = join(args.startup_dir, "sim_conf.toml")
    elif args.device_file and args.config_file:
        device_file = args.device_file
        config_file = args.config_file
    else:
        parser.error(
            "Either --startup-dir or both --device-file and --config-file must be provided"
        )

    map_file = args.beam_map
    if map_file is None and args.startup_dir:
        candidate = join(args.startup_dir, "beam_map.toml")
        if exists(candidate) and default_overlay(candidate):
            map_file = candidate
    beam_map = None
    if map_file is not None and not args.no_beam_map:
        print(f"Reading the beam from the beam map IOC for {map_file}")
        beam_map = load_map(map_file)

    config = generate_device_config(
        device_file,
        config_file,
        translation_dict=sim_loaders(config_file),
        sim_mode=True,
    )
    config = select_process(config, args.process)
    if args.process:
        print(f"Sim process {args.process}: {', '.join(config) or 'no devices'}")
    ioc = Beamline(
        config=config,
        config_dir=dirname(config_file),
        beam_map=beam_map,
        process=args.process,
        **ioc_options,
    )
    pvdb = dict(ioc.pvdb)
    if args.process:
        # The main process serves the beamline's own PVs
        pvdb.pop(ioc.beam_available.pvname)

    run(pvdb, **run_options)


if __name__ == "__main__":
    main()
