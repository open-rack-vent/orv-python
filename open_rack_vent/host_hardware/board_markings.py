"""
Common board markings on the various connectors available to user on the ORV PCBs
"""

from enum import Enum


class BoardMarkingActiveLowPWM(str, Enum):
    """
    Board markings for the active low (NMOS) PWM controlled outputs.
    """

    onboard = "ONBOARD"
    pn1 = "PN1"
    pn2 = "PN2"
    pn3 = "PN3"
    pn4 = "PN4"
    pn5 = "PN5"


class BoardMarkingTempPin(str, Enum):
    """
    Board markings for the different temperature sensor inputs. They are designed to be connected to
    3950K 10K ohm NTC thermistor probes.
    """

    tmp0 = "TMP0"
    tmp1 = "TMP1"
    tmp2 = "TMP2"
    tmp3 = "TMP3"
    tmp4 = "TMP4"
    tmp5 = "TMP5"
    tmp6 = "TMP6"


class BoardMarkingActiveLowGPIO(str, Enum):
    """
    Board markings for the active low (NMOS) GPIO controlled outputs. Only suitable for on/off
    control.
    """

    gn0 = "GN0"
    gn1 = "GN1"
    gn2 = "GN2"
    gn3 = "GN3"


class OnboardLED(str, Enum):
    """
    Board markings for the LEDs.
    """

    run = "RUN"
    web = "WEB"
    fault = "FAULT"
