"""
Models the ORV in MQTT so it can be controlled via Home Assistant (or other MQTT interfaces).
"""

import itertools
import json
import logging
import statistics
import time
from typing import Callable, Dict

import paho.mqtt.client as mqtt

from open_rack_vent.host_hardware import OpenRackVentHardwareInterface
from open_rack_vent.host_hardware.board_interface_types import PCBRevision, RackLocation

LOGGER = logging.getLogger(__name__)


def _model_from_pcb_revision(pcb_revision: PCBRevision) -> str:
    """
    Populates the "Model" field in the config payloads.
    :param pcb_revision: Could in future include more than this.
    :return: String for model field.
    """

    return f"ORV: {pcb_revision.value}"


def make_on_connect(
    device_id: str,
    orv_hardware_interface: "OpenRackVentHardwareInterface",
    pcb_revision: "PCBRevision",
) -> Callable[[mqtt.Client, None, Dict[str, bool], int], None]:
    """
    Create a stateless MQTT `on_connect` callback that publishes Home Assistant
    autodiscovery messages for all control surfaces.

    :param device_id: The MQTT device ID / topic prefix for this device.
    :param orv_hardware_interface: Interface providing access to fans and temperature sensors.
    :param pcb_revision: Hardware revision used to generate the MQTT device model.
    :return: Callable suitable for `mqtt.Client.on_connect`.
    """

    def on_connect(client: mqtt.Client, _userdata: None, flags: Dict[str, bool], rc: int) -> None:
        """
        Callback invoked when the MQTT client connects to the broker.

        :param client: Active MQTT client instance.
        :param _userdata: MQTT userdata (unused in this application).
        :param flags: Connection flags from the broker.
        :param rc: Connection result code (0 = success).
        :return: None
        """
        LOGGER.info(f"MQTT connected with result code {rc}, flags: {flags}")

        # Publish online status
        client.publish(f"{device_id}/status/online", "online", retain=True)

        # Subscribe to all fan set commands
        client.subscribe(f"{device_id}/fan/+/set")

        try:
            # Device metadata for HA discovery
            device = {
                "identifiers": [f"open_rack_vent_{device_id}"],
                "manufacturer": "OpenRackVent",
                "model": _model_from_pcb_revision(pcb_revision=pcb_revision),
                "name": "Open Rack Vent",
            }

            availability_topic = f"{device_id}/status/online"

            # Publish temperature sensors
            for temperature_rack_location in orv_hardware_interface.temperature_readers.keys():
                unique_id = f"{temperature_rack_location.value}_temperature"
                topic = f"homeassistant/sensor/{unique_id}/config"

                client.publish(
                    topic,
                    json.dumps(
                        {
                            "name": f"ORV Temperature {temperature_rack_location.value}",
                            "state_topic": (
                                f"{device_id}/temperature/{temperature_rack_location.value}"
                            ),
                            "unique_id": unique_id,
                            "device_class": "temperature",
                            "unit_of_measurement": "°C",
                            "device": device,
                            "availability_topic": availability_topic,
                        }
                    ),
                    retain=True,
                )

            # Publish fan controls
            for fan_rack_location in orv_hardware_interface.fan_controllers.keys():
                unique_id = f"{fan_rack_location.value}_fan"
                topic = f"homeassistant/number/{unique_id}/config"

                client.publish(
                    topic,
                    json.dumps(
                        {
                            "name": f"ORV Fan Power {fan_rack_location.value}",
                            "state_topic": f"{device_id}/fan/{fan_rack_location.value}/state",
                            "command_topic": f"{device_id}/fan/{fan_rack_location.value}/set",
                            "unique_id": unique_id,
                            "min": 0,
                            "max": 1,
                            "step": 0.01,
                            "device": device,
                            "availability_topic": availability_topic,
                            "value_template": "{{ value_json.power }}",
                        }
                    ),
                    retain=True,
                )

        except Exception as e:  # pylint: disable=broad-except
            LOGGER.error(f"Failed to publish discovery: {e}")

    return on_connect


def make_on_message(
    orv_hardware_interface: OpenRackVentHardwareInterface,
    device_id: str,
) -> Callable[[mqtt.Client, None, mqtt.MQTTMessage], None]:
    """
    Create a stateless MQTT `on_message` callback for fan control.

    This function handles messages on fan set topics in the format:
    ``<device_id>/fan/<rack_location>/set``

    The payload should be a JSON object:
    ``{"power": <float between 0.0 and 1.0>}``

    :param orv_hardware_interface: OpenRackVentHardwareInterface containing fan controller mappings.
    :param device_id: Base MQTT topic prefix for this device.
    :return: Callable suitable for `mqtt.Client.on_message`.
    """

    def on_message(client: mqtt.Client, _userdata: None, msg: mqtt.MQTTMessage) -> None:
        """
        Handle incoming MQTT messages for fan control.

        :param client: Active MQTT client instance involved in this interaction.
        :param _userdata: MQTT userdata (globally, userdata is never used in this application).
        :param msg: MQTT message containing topic and payload.
        """
        try:
            topic_parts = msg.topic.split("/")

            # Expect: <device_id>/fan/<rack_location>/set
            if len(topic_parts) != 4 or topic_parts[1] != "fan" or topic_parts[3] != "set":
                return  # Not a fan set command, ignore

            _, _, rack_location_raw, _ = topic_parts

            rack_location = RackLocation(rack_location_raw)

            power = float(msg.payload.decode())

            # Lookup fan controllers by rack location
            controls = orv_hardware_interface.fan_controllers.get(rack_location)
            if not controls:
                print(f"No fan controllers found for rack_location={rack_location}")
                return

            # Execute all fan controls
            _commands = list(itertools.chain.from_iterable(fn(power) for fn in controls))

            # Publish new state to MQTT
            client.publish(
                f"{device_id}/fan/{rack_location}/state",
                json.dumps({"power": power}),
                retain=True,
            )
        except Exception as e:  # pylint: disable=broad-except
            LOGGER.error(f"Error handling MQTT message {msg.topic}: {e}")

    return on_message


def run_open_rack_vent_mqtt(  # pylint: disable=too-many-positional-arguments
    orv_hardware_interface: OpenRackVentHardwareInterface,
    broker_host: str,
    device_id: str,
    pcb_revision: PCBRevision,
    publish_interval: float,
    mqtt_username: str,
    mqtt_password: str,
) -> None:
    """
    Start the stateless MQTT interface for the Open Rack Vent hardware.

    :param orv_hardware_interface: OpenRackVentHardwareInterface, the main API for controlling and
    listing control surfaces.
    :param broker_host: MQTT broker hostname
    :param device_id: Base MQTT topic prefix
    :param pcb_revision: Consumed in setting the "Model" Field in the config endpoints.
    :param publish_interval: How often to send new values.
    :param mqtt_username: MQTT username, used to authenticate with MQTT.
    :param mqtt_password: Used to authenticate with MQTT.
    """
    mqtt_client = mqtt.Client(client_id=f"{device_id}_controller")

    mqtt_client.will_set(f"{device_id}/status/online", "offline", retain=True)

    mqtt_client.on_connect = make_on_connect(
        orv_hardware_interface=orv_hardware_interface,
        device_id=device_id,
        pcb_revision=pcb_revision,
    )

    # Haven't re-worked below this line
    mqtt_client.on_message = make_on_message(orv_hardware_interface, device_id)
    mqtt_client.username_pw_set(mqtt_username, mqtt_password)
    mqtt_client.connect(broker_host, 1883, 60)
    mqtt_client.loop_start()

    try:
        # Periodically publish info to the MQTT broker.

        while True:
            try:
                for location, readers in orv_hardware_interface.temperature_readers.items():

                    # Compute average temperature across all readers at this location
                    average_temperature = statistics.mean([read_fn() for read_fn in readers])

                    # Publish to the state_topic defined in discovery
                    topic = f"{device_id}/temperature/{location.value}"
                    payload = json.dumps({"temperature": average_temperature})

                    mqtt_client.publish(topic, payload, retain=True)
                    LOGGER.debug(f"Published temperature {average_temperature:.2f}°C to {topic}")
            except Exception as e:  # pylint: disable=broad-except
                logging.error(f"Failed to publish temperatures: {e}")
            time.sleep(publish_interval)

    except KeyboardInterrupt:
        LOGGER.info("Shutting down MQTT interface...")
    finally:
        mqtt_client.publish(f"{device_id}/status/online", "offline", retain=True)
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        LOGGER.info("Disconnected from MQTT broker.")
