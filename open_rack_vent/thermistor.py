"""
Functions for reading temperature values off of a 10K 3950 NTC thermistor.
The resistor is attached to 3.3V and a 10K pulldown resistor which is attached to ground.
See schematic for more details.
"""

import json
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Union

from open_rack_vent import assets

RESISTANCE_OF_PULLDOWN = 10_000
U_12_MAX = 4096


def _counts_to_resistance(
    adc_counts: int,
    pulldown_resistance: int,
    max_adc_count: int,
) -> float:
    """
    Convert ADC counts into resistance.
    :param adc_counts: The ADC interface that is associated with the pin connected to the
    thermistor.
    :param pulldown_resistance: The value of the pulldown resistor in ohms.
    :param max_adc_count: The ADC count (in the u16 number space) for V_in, the max value that could
    be read from the ADC.
    :param samples: The number of samples to take to average for the measurement.
    :return: The resistance in Ohms as a float.
    """
    return float((pulldown_resistance * (max_adc_count / adc_counts)) - pulldown_resistance)


def _closest_to_value(
    value: float, list_of_values: Union[Sequence[int], Sequence[float]]
) -> Union[int, float]:
    """
    Given a value, and a list of values, find the closest value in the list to the input.
    :param value: Value to find in list.
    :param list_of_values: Candidate output values.
    :return: The value closest to `value` in `list_of_values`.
    """
    return list_of_values[
        min(range(len(list_of_values)), key=lambda i: abs(list_of_values[i] - value))
    ]


def _read_resistance_to_temperature(
    lookup_json_path: Path,
) -> Dict[float, float]:
    """
    Reads a local json file that contains a series of keys mapping temperature to resistance.
    :param lookup_json_path: Path to the json file.
    :return: The mapping, from resistance to temperature. This is a reversal of the input format.
    """

    with open(lookup_json_path, "r", encoding="utf-8") as f:
        lookup_dict: Dict[str, str] = json.load(f)

        # Need to multiply by 1000 because file is in kOhm
        resistance_to_temperature: Dict[float, float] = {
            float(resistance_str): float(temperature_str)
            for temperature_str, resistance_str in lookup_dict.items()
        }

    return resistance_to_temperature


def _thermistor_temperature_resistance(
    resistance: float, resistance_to_temperature: Dict[float, float]
) -> float:
    """
    Given a resistance and lookup, convert to temperature.
    :param resistance: Thermistor resistance.
    :param resistance_to_temperature: A dict mapping resistance values to their corresponding
    temperature. Units are ohms and degrees Celsius.
    :return: Temperature in degrees Celsius.
    """

    return resistance_to_temperature[
        _closest_to_value(
            resistance,
            list(resistance_to_temperature.keys()),
        )
    ]


def create_adc_counts_to_temperature_converter(
    lookup_json_path: Path = assets.B2550_10K_3950K_NTC_THERMISTOR_LOOKUP_PATH,
    pulldown_resistance: int = RESISTANCE_OF_PULLDOWN,
    max_adc_count: int = U_12_MAX,
) -> Callable[[int], float]:
    """
    Creates a callable function that converts the ADC counts to temperature. It does this by looking
    up by calculating the resistance and looking up the resistance in a lookup.
    :param lookup_json_path: Path to resistance->temp mapping.
    :param pulldown_resistance: Circuit dependant pulldown resistance.
    :param max_adc_count: The ADC count (in the u16 number space) for V_in, the max value that will
    be seen.
    :return: ADC counts to temperature function.
    """

    resistance_to_temperature: Dict[float, float] = _read_resistance_to_temperature(
        lookup_json_path=lookup_json_path
    )

    def adc_counts_to_temperature(adc_counts: int) -> Optional[float]:
        """
        Output function, uses the same loaded in mapping.
        :param adc_counts: ADC counts.
        :return: Temperature in degrees Celsius. If something goes wrong, a `None` is returned.
        """
        try:
            resistance_ohms = _counts_to_resistance(
                adc_counts=adc_counts,
                max_adc_count=max_adc_count,
                pulldown_resistance=pulldown_resistance,
            )

            return _thermistor_temperature_resistance(
                resistance=resistance_ohms,
                resistance_to_temperature=resistance_to_temperature,
            )
        except Exception as _exn:  # pylint: disable=broad-except
            return None

    return adc_counts_to_temperature
