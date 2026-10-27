"""Serve the example map's input PVs, writable, for the IOC tests."""

from caproto import ChannelDouble, ChannelInteger
from caproto.server import run

pvdb = {
    "NBS_SIM:fe_shutter:Pos-Sts": ChannelInteger(value=0),
    "XF:07IDA-OP{Mir:M1-Ax:X}Mtr_MON": ChannelDouble(value=15.0),
    "NBS_SIM:beam_available": ChannelInteger(value=1),
}

if __name__ == "__main__":
    run(pvdb)
