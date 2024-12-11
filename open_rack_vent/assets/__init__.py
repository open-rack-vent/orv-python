"""Uses pathlib to make referencing test assets by path easier."""

from pathlib import Path

_ASSETS_DIRECTORY = Path(__file__).parent.resolve()

# These are the 'barrel' type thermistors used in the original tesla cooler and other projects.
B2550_10K_3950K_NTC_THERMISTOR_LOOKUP_PATH = _ASSETS_DIRECTORY.joinpath(
    "10K_B2550_ 3950K_NTC_temperature_to_resistance_lookup.json"
)
