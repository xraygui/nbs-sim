import toml
from copy import deepcopy
from importlib import import_module

def simpleResolver(fullclassname):
    """
    Resolve a full class name to a class object.

    Parameters
    ----------
    fullclassname : str
        The full class name to resolve.

    Returns
    -------
    type
        The class object resolved from the full class name.
    """
    class_name = fullclassname.split(".")[-1]
    module_name = ".".join(fullclassname.split(".")[:-1])
    module = import_module(module_name)
    cls = getattr(module, class_name)
    return cls


def createIOCDevice(info, cls=None, parent=None):
    """
    Instantiate a device with given information.

    Parameters
    ----------
    device_key : str
        The key identifying the device.
    info : dict
        The information dictionary for the device.
    cls : type, optional
        The class to instantiate the device with. If not provided, it will be resolved from the info dictionary.
    namespace : dict, optional
        The namespace to add the instantiated device to.

    Returns
    -------
    object
        The instantiated device.
    """
    device_info = deepcopy(info)
    if cls is not None:
        device_info.pop("_target", None)
    elif device_info.get("_target", None) is not None:
        cls = simpleResolver(device_info.pop("_target"))
    else:
        raise KeyError("Could not find '_target' in {}".format(device_info))

    popkeys = [key for key in device_info if key.startswith("_")]
    for key in popkeys:
        device_info.pop(key)

    prefix = device_info.pop("prefix", "")
    device = cls(prefix, parent=parent, **device_info)
    if parent is not None:
        parent.pvdb.update(**device.pvdb)
    return device


def loadDeviceConfig(filename, namespace=None):
    """
    Load device configuration from a file and instantiate devices.

    Parameters
    ----------
    filename : str
        The path to the file containing the device configuration.
    namespace : dict, optional
        The namespace to add the instantiated devices to.

    Returns
    -------
    dict
        A dictionary of instantiated devices.
    """
    db = loadConfigDB(filename)
    device_dict = {}
    for key, info in db.items():
        device = instantiateDevice(key, info, namespace=namespace)
        device_dict[key] = device
    return device_dict
