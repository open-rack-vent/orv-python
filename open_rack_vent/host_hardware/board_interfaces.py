"""
Main export module for the `OpenRackVentHardwareInterface`s. Go from the user's hardware request
to the interface.
"""

from open_rack_vent.host_hardware.board_interface_types import (
    HardwarePlatform,
    OpenRackVentHardwareInterface,
    PCBRevision,
    WireMapping,
)
from open_rack_vent.host_hardware.interfaces import beaglebone_black


def create_hardware_interface(
    pcb_revision: PCBRevision, platform: HardwarePlatform, wire_mapping: WireMapping
) -> OpenRackVentHardwareInterface:
    """
    CLI frontend for getting a hardware interface.
    :param pcb_revision: Comes from user, describes which PCB version is attached to the hardware
    platform.
    :param platform: Comes from user, describes which hardware platform is attached to the PCB.
    :param wire_mapping: Comes from user, describes how the different components inside the rack
    are attached to the PCB.
    :return: The NT of callables to interact with the Open Rack Vent outputs and inputs.
    :raises ValueError: Should unsupported versions or impossible mappings be passed in.
    """

    if pcb_revision == PCBRevision.v100 and platform == HardwarePlatform.beaglebone_black:
        return beaglebone_black.create_interface(
            board_marking_lookup=beaglebone_black.BBB_V100_BOARD_MARKINGS_TO_PINS,
            wire_mapping=wire_mapping,
        )
    else:
        raise ValueError(f"Unsupported PCB Revision: {pcb_revision.value}")
