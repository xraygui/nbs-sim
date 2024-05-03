from caproto.server import PVGroup, SubGroup, template_arg_parser, pvproperty, run, PvpropertyDouble
from caproto.ioc_examples.fake_motor_record import FakeMotor
import asyncio
from time import time
from load import createIOCDevice
from autoconf import load_device_config


class Beamline(PVGroup):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transmission_list = []
        self.motors = {}

    def current_func(self):
        t = time.monotonic() % (300)
        if t < 270:
            current = 500 - 50*t/270
        else:
            current = 500 - 50*(300 - t)/30
        return current

    def intensity_func(self):
        base = self.current_func()
        for trans_dev in self.transmission_list:
            base *= trans_dev.transmission.value
        return base


def create_ioc(configuration, prefix="", **ioc_options):
    'Create groups based on prefixes passed in from groups_a, groups_b'

    ioc = Beamline(prefix="", **ioc_options)
    for groupname, group in configuration.items():
        setattr(ioc, groupname, {})
        groupdict = getattr(ioc, groupname)
        for key, device_info in group.items():
            groupdict[key] = createIOCDevice(device_info, parent=ioc)
    return ioc


def main(argv=None):
    parser, split_args = template_arg_parser(desc="Simulation IOC Generator", default_prefix="SIM:")
    parser.add_argument("--device-file", required=True, help="Location of device file")
    parser.add_argument("--simulation-file", required=True, help="Location of simulation file")

    args = parser.parse_args()
    ioc_options, run_options = split_args(args)

    config = load_device_config(args.device_file, args.simulation_file)

    ioc = create_ioc(config, **ioc_options)
    run(ioc.pvdb, **run_options)


if __name__ == "__main__":
    main()
