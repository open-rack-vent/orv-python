# Changelog

0.3.1 - (2026-01-07)
------------------

* Fixes two bugs in the MQTT temperature reporting code.


0.3.0 - (2025-11-26)
------------------

* Implements MQTT control API for integration with homeassistant.
* Cleaned up CLI launcher code so both web and mqtt APIs can run at the same time if desired.
* Added CLI entrypoint `render-systemd` for creating systemd units that run at startup.
* General repo quality lift pre-publication.


0.2.0 - (2025-11-18)
------------------

* Created an abstraction layer, the `OpenRackVentHardwareInterface` between the different UI code
like the web interface and the hardware.
* CLI args produce these `OpenRackVentHardwareInterface` based on the hardware in use by user.
* Better mapping of board layout -> pins, board markers -> pins etc.
* Main entrypoint is now a proper click CLI interface. 


0.1.0 - (2025-08-05)
------------------

* First working version. Supports driving fans controlled via the web UI.


0.0.1 - (2024-12-03)
------------------

* Project begins
