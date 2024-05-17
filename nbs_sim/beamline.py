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
from scipy.special import erf
from os.path import join, dirname
from scipy.interpolate import UnivariateSpline
from nbs_core.beamline import BeamlineModel
from nbs_core.autoconf import generate_device_config
from nbs_core.autoload import loadFromConfig

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def norm_erf(x, width=1):
    return 0.5 * (erf(2.0 * x / width) + 1)


class Beamline(BeamlineModel, PVGroup):
    def __init__(self, *args, config, **kwargs):
        super().__init__(*args, devices={}, groups={}, roles={}, **kwargs)
        self.load_detector_data()
        devices, groups, roles = loadFromConfig(config, createIOCDevice, parent=self)
        self.loadDevices(devices, groups, roles)
        self.transmission_list = []

        self.configure_beamline()

    def load_detector_data(self):
        dirpath = dirname(__file__)
        print(dirpath)
        data = np.load(join(dirpath, "all_edges.npz"))
        refdata = np.load(join(dirpath, "all_ref.npz"))
        self.yspl = UnivariateSpline(data["x"], data["y"], s=0)
        self.refspl = UnivariateSpline(refdata["x"], refdata["y"], s=0)

    def add_to_transmission(self, key):
        device = self.devices.get(key, None)
        if device is not None:
            print(f"Adding {key} to transmission")
            self.transmission_list.append(device)

    def current_func(self):
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
        if self.primary_manipulator is not None:
            dist = self.primary_manipulator.distance_to_beam()
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

    def configure_shutters(self):
        for key, device in self.shutters.items():
            self.add_to_transmission(device)

    def configure_apertures(self):
        for key, device in self.apertures.items():
            self.add_to_transmission(device)

    def configure_gatevalves(self):
        for key, device in self.gatevalves.items():
            self.add_to_transmission(device)

    def configure_detectors(self):
        pass

    def configure_motors(self):
        pass


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

    config = generate_device_config(device_file, config_file)
    ioc = Beamline(config=config, **ioc_options)

    run(ioc.pvdb, **run_options)


if __name__ == "__main__":
    main()
