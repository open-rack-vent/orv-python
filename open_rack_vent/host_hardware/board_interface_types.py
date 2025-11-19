"""
Defines the BoardInterface, a collection of callables that facilitate "low level" interaction with
the hardware components on the PCB. This "BoardInterface" is the object that the different control
methods (the REST API, the MQTT interface with Home Assistant) interact with.
"""

from enum import Enum
from typing import Callable, List, NamedTuple

from pydantic import BaseModel

from open_rack_vent.host_hardware import board_markings


class HardwarePlatform(str, Enum):
    """
    Different supported hardware backends that can drive the Open Rack Vent PCBs.
    This is mostly future-proofing `create_hardware_interface`, there is no intent to support
    other hardware platforms at the time of writing.
    """

    beaglebone_black = "BeagleBoneBlack"


class PCBRevision(str, Enum):
    """
    Different hardware revisions of the Open Rack Vent PCB.
    """

    v100 = "v1.0.0"


class WireMappingVersion(str, Enum):
    """
    Because the associated `WireMapping` is coming from an environment variable (or config file)
    this data exists outside the code and therefor needs a version to maintain compatibility with
    the code.
    """

    version_1 = "1"


class WireMapping(BaseModel):
    """
    Defines the user configurable data structure that describes how the connections are made to the
    ORV pcb.
    """

    version: WireMappingVersion

    upper_intake_fans: List[board_markings.BoardMarkingActiveLowPWM]
    lower_intake_fans: List[board_markings.BoardMarkingActiveLowPWM]
    upper_exhaust_fans: List[board_markings.BoardMarkingActiveLowPWM]

    intake_temperature_pins: List[board_markings.BoardMarkingTempPin]
    exhaust_temperature_pins: List[board_markings.BoardMarkingTempPin]
    environment_temperature_pins: List[board_markings.BoardMarkingTempPin]


class OpenRackVentHardwareInterface(NamedTuple):
    """
    Provides a unified interface for interacting with the Open Rack Vent hardware. This interface
    could be ported to other hardware backends, like the Raspberry Pi and the rest of the
    application would function the same.
    """

    set_onboard_led: Callable[[board_markings.OnboardLED, bool], List[str]]

    read_all_intake_temperatures: Callable[[], List[float]]
    read_all_exhaust_temperatures: Callable[[], List[float]]

    lower_intake_fan_controls: List[Callable[[float], List[str]]]
    upper_intake_fan_controls: List[Callable[[float], List[str]]]
    upper_exhaust_fan_controls: List[Callable[[float], List[str]]]
