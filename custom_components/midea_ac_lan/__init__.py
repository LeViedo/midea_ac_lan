import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from .const import (
    DOMAIN,
    CONF_KEY,
    CONF_MODEL,
    DEVICES,
    EXTRA_SENSOR,
    EXTRA_SWITCH,
    EXTRA_CONTROL,
    ALL_PLATFORM,
)
from .midea_devices import MIDEA_DEVICES

from homeassistant.core import HomeAssistant
from homeassistant.const import (
    CONF_NAME,
    CONF_TOKEN,
    CONF_HOST,
    CONF_IP_ADDRESS,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_DEVICE_ID,
    CONF_TYPE,
    CONF_CUSTOMIZE,
    TEMP_FAHRENHEIT,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID
)
from .midea.devices import device_selector

_LOGGER = logging.getLogger(__name__)


async def update_listener(hass, config_entry):
    for platform in ALL_PLATFORM:
        await hass.config_entries.async_forward_entry_unload(config_entry, platform)
    for platform in ALL_PLATFORM:
        hass.async_create_task(hass.config_entries.async_forward_entry_setup(
            config_entry, platform))
    device_id = config_entry.data.get(CONF_DEVICE_ID)
    customize = config_entry.options.get(
        CONF_CUSTOMIZE, ""
    )
    ip_address = config_entry.options.get(
        CONF_IP_ADDRESS, None
    )
    dev = hass.data[DOMAIN][DEVICES].get(device_id)
    if dev:
        dev.set_customize(customize)
        if ip_address:
            dev.set_ip_address(ip_address)


async def async_setup(hass: HomeAssistant, hass_config: dict):
    hass.data.setdefault(DOMAIN, {})
    attributes = []
    for device_entities in MIDEA_DEVICES.values():
        for attribute_name, attribute in device_entities.get("entities").items():
            if attribute.get("type") in EXTRA_SWITCH and attribute_name.value not in attributes:
                attributes.append(attribute_name.value)

    def service_set_ac_fan_speed(service):
        device_id = service.data.get("device_id")
        fan_speed = service.data.get("fan_speed")
        if fan_speed == "auto":
            fan_speed = 102
        dev = hass.data[DOMAIN][DEVICES].get(device_id)
        if dev and dev.device_type == 0xac:
            dev.set_attribute(attr="fan_speed", value=fan_speed)

    def service_set_attribute(service):
        device_id = service.data.get("device_id")
        attr = service.data.get("attribute")
        value = service.data.get("value")
        dev = hass.data[DOMAIN][DEVICES].get(device_id)
        if dev:
            if attr == "fan_speed" and value == "auto":
                value = 102
            item = MIDEA_DEVICES.get(dev.device_type).get("entities").get(attr)
            if item and (item.get("type") in EXTRA_SWITCH or
                         (dev.device_type == 0xAC and attr == "fan_speed" and value in range(0, 103))):
                dev.set_attribute(attr=attr, value=value)
            else:
                _LOGGER.error(f"Appliance [{device_id}] has no attribute {attr} or invalid value")

    def service_send_command(service):
        device_id = service.data.get("device_id")
        cmd_type = service.data.get("cmd_type")
        cmd_body = service.data.get("cmd_body")
        try:
            cmd_body = bytearray.fromhex(cmd_body)
        except ValueError:
            _LOGGER.error(f"Appliance [{device_id}] invalid cmd_body, a hexadecimal string required")
            return
        dev = hass.data[DOMAIN][DEVICES].get(device_id)
        if dev:
            dev.send_command(cmd_type, cmd_body)

    hass.services.async_register(
        DOMAIN,
        "set_ac_fan_speed",
        service_set_ac_fan_speed,
        schema=vol.Schema(
            {
                vol.Required("device_id"): vol.Coerce(int),
                vol.Required("fan_speed"): vol.Any(vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
                                                   vol.All(str, vol.In(["auto"])))
            }
        )
    )

    hass.services.async_register(
        DOMAIN,
        "set_attribute",
        service_set_attribute,
        schema=vol.Schema(
            {
                vol.Required("device_id"): vol.Coerce(int),
                vol.Required("attribute"): vol.In(attributes),
                vol.Required("value"): vol.Any(cv.boolean, str)
            }
        )
    )

    hass.services.async_register(
        DOMAIN,
        "send_command",
        service_send_command,
        schema=vol.Schema(
            {
                vol.Required("device_id"): vol.Coerce(int),
                vol.Required("cmd_type"): vol.In([2, 3]),
                vol.Required("cmd_body"): str
            }
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry):
    name = config_entry.data.get(CONF_NAME)
    device_id = config_entry.data.get(CONF_DEVICE_ID)
    if name is None:
        name = f"{device_id}"
    device_type = config_entry.data.get(CONF_TYPE)
    if device_type is None:
        device_type = 0xac
    token = config_entry.data.get(CONF_TOKEN)
    key = config_entry.data.get(CONF_KEY)
    ip_address = config_entry.options.get(CONF_IP_ADDRESS, None)
    if not ip_address:
        ip_address = config_entry.data.get(CONF_IP_ADDRESS)
    port = config_entry.data.get(CONF_PORT)
    model = config_entry.data.get(CONF_MODEL)
    protocol = config_entry.data.get(CONF_PROTOCOL)
    customize = config_entry.options.get(CONF_CUSTOMIZE)
    if protocol == 3 and (key is None or key is None):
        _LOGGER.error("For V3 devices, the key and the token is required.")
        return False
    device = device_selector(
        name=name,
        device_id=device_id,
        device_type=device_type,
        ip_address=ip_address,
        port=port,
        token=token,
        key=key,
        protocol=protocol,
        model=model,
        customize=customize,
    )
    if device:
        device.open()
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        if DEVICES not in hass.data[DOMAIN]:
            hass.data[DOMAIN][DEVICES] = {}
        hass.data[DOMAIN][DEVICES][device_id] = device
        for platform in ALL_PLATFORM:
            hass.async_create_task(hass.config_entries.async_forward_entry_setup(
                config_entry, platform))
        config_entry.add_update_listener(update_listener)
        return True
    return False


async def async_unload_entry(hass: HomeAssistant, config_entry):
    device_id = config_entry.data.get(CONF_DEVICE_ID)
    if device_id is not None:
        dm = hass.data[DOMAIN][DEVICES].get(device_id)
        if dm is not None:
            dm.close()
        hass.data[DOMAIN][DEVICES].pop(device_id)
    for platform in ALL_PLATFORM:
        await hass.config_entries.async_forward_entry_unload(config_entry, platform)
    return True
