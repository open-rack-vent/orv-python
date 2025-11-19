"""
Defines the central hardware abstraction. The `OpenRackVentHardwareInterface` is all the rest of
the application gets access to w/r/t hardware.
"""

from open_rack_vent.host_hardware.board_interface_types import (
    HardwarePlatform,
    OpenRackVentHardwareInterface,
    PCBRevision,
    WireMapping,
)
from open_rack_vent.host_hardware.board_interfaces import create_hardware_interface
