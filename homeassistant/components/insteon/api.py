"""Web socket API for Insteon devices."""

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import callback
from pyinsteon import devices
from pyinsteon.constants import ALDBStatus
from pyinsteon.topics import (
    ALDB_STATUS_CHANGED,
    DEVICE_LINK_CONTROLLER_CREATED,
    DEVICE_LINK_RESPONDER_CREATED,
)
from pyinsteon.utils import subscribe_topic, unsubscribe_topic

from .const import DOMAIN
from .properties import get_properties, set_property
from .schemas import ALDB_RECORD_SCHEMA

TYPE = "type"
ID = "id"
DEVICE_ID = "device_id"
DEVICE_ADDRESS = "device_address"
ALDB_RECORD = "record"
PROPERTY_NAME = "name"
PROPERTY_VALUE = "value"
HA_DEVICE_NOT_FOUND = "ha_device_not_found"
INSTEON_DEVICE_NOT_FOUND = "insteon_device_not_found"


def compute_device_name(ha_device):
    """Return the HA device name."""
    return ha_device.name_by_user if ha_device.name_by_user else ha_device.name


def get_insteon_device_from_ha_device(ha_device):
    """Return the Insteon device from an HA device."""
    for identifier in ha_device.identifiers:
        if len(identifier) > 1 and identifier[0] == DOMAIN and devices[identifier[1]]:
            return devices[identifier[1]]
    return None


async def async_device_name(dev_registry, address):
    """Get the Insteon device name from a device registry id."""
    ha_device = dev_registry.async_get_device(
        identifiers={(DOMAIN, str(address))}, connections=set()
    )
    if not ha_device:
        device = devices[address]
        if device:
            return f"{device.description} ({device.model})"
        return ""
    return compute_device_name(ha_device)


async def async_aldb_record_to_dict(dev_registry, record, dirty=False):
    """Convert an ALDB record to a dict."""
    return {
        "mem_addr": record.mem_addr,
        "in_use": record.is_in_use,
        "mode": "C" if record.is_controller else "R",
        "highwater": record.is_high_water_mark,
        "group": record.group,
        "target": str(record.target),
        "target_name": await async_device_name(dev_registry, record.target),
        "data1": record.data1,
        "data2": record.data2,
        "data3": record.data3,
        "dirty": dirty,
    }


def notify_device_not_found(connection, msg, text):
    """Notify the caller that the device was not found."""
    connection.send_message(
        websocket_api.error_message(msg[ID], websocket_api.const.ERR_NOT_FOUND, text)
    )


async def async_reload_and_save_aldb(hass, device):
    """Add default links to an Insteon device."""
    if device == devices.modem:
        await device.aldb.async_load()
    else:
        await device.aldb.async_load(refresh=True)
    await devices.async_save(workdir=hass.config.config_dir)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {vol.Required(TYPE): "insteon/device/get", vol.Required(DEVICE_ID): str}
)
async def websocket_get_device(hass, connection, msg):
    """Get an Insteon device."""
    dev_registry = await hass.helpers.device_registry.async_get_registry()
    ha_device = dev_registry.async_get(msg[DEVICE_ID])
    if not ha_device:
        notify_device_not_found(connection, msg, HA_DEVICE_NOT_FOUND)
        return
    device = get_insteon_device_from_ha_device(ha_device)
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return
    ha_name = compute_device_name(ha_device)
    device_info = {
        "name": ha_name,
        "address": str(device.address),
        "is_battery": device.is_battery,
        "aldb_status": str(device.aldb.status),
    }
    connection.send_result(msg[ID], device_info)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {vol.Required(TYPE): "insteon/aldb/get", vol.Required(DEVICE_ADDRESS): str}
)
async def websocket_get_aldb(hass, connection, msg):
    """Get the All-Link Database for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    # Convert the ALDB to a dict merge in pending changes
    aldb = {mem_addr: device.aldb[mem_addr] for mem_addr in device.aldb}
    aldb.update(device.aldb.pending_changes)
    changed_records = list(device.aldb.pending_changes.keys())

    dev_registry = await hass.helpers.device_registry.async_get_registry()

    records = [
        await async_aldb_record_to_dict(
            dev_registry, aldb[mem_addr], mem_addr in changed_records
        )
        for mem_addr in aldb
    ]

    connection.send_result(msg[ID], records)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/change",
        vol.Required(DEVICE_ADDRESS): str,
        vol.Required(ALDB_RECORD): ALDB_RECORD_SCHEMA,
    }
)
async def websocket_change_aldb_record(hass, connection, msg):
    """Change an All-Link Database record for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    record = msg[ALDB_RECORD]
    device.aldb.modify(
        mem_addr=record["mem_addr"],
        in_use=record["in_use"],
        group=record["group"],
        controller=record["mode"].lower() == "c",
        target=record["target"],
        data1=record["data1"],
        data2=record["data2"],
        data3=record["data3"],
    )
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/create",
        vol.Required(DEVICE_ADDRESS): str,
        vol.Required(ALDB_RECORD): ALDB_RECORD_SCHEMA,
    }
)
async def websocket_create_aldb_record(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    record = msg[ALDB_RECORD]
    device.aldb.add(
        group=record["group"],
        controller=record["mode"].lower() == "c",
        target=record["target"],
        data1=record["data1"],
        data2=record["data2"],
        data3=record["data3"],
    )
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/write",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_write_aldb(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    await device.aldb.async_write()
    hass.async_create_task(async_reload_and_save_aldb(hass, device))
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/load",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_load_aldb(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    hass.async_create_task(async_reload_and_save_aldb(hass, device))
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/reset",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_reset_aldb(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    device.aldb.clear_pending()
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/add_default_links",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_add_default_links(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    device.aldb.clear_pending()
    await device.async_add_default_links()
    hass.async_create_task(async_reload_and_save_aldb(hass, device))
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/get",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_get_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    properties, schema = get_properties(device)

    connection.send_result(msg[ID], {"properties": properties, "schema": schema})


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/change",
        vol.Required(DEVICE_ADDRESS): str,
        vol.Required(PROPERTY_NAME): str,
        vol.Required(PROPERTY_VALUE): vol.Any(list, int, float, bool, str),
    }
)
async def websocket_change_properties_record(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    set_property(device, msg[PROPERTY_NAME], msg[PROPERTY_VALUE])
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/write",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_write_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    await device.async_write_op_flags()
    await device.async_write_ext_properties()
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/load",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_load_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    await device.async_read_op_flags()
    await device.async_read_ext_properties()
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/reset",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_reset_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    for prop in device.operating_flags:
        device.operating_flags[prop].new_value = None
    for prop in device.properties:
        device.properties[prop].new_value = None
    connection.send_result(msg[ID])


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/notify",
        vol.Required(DEVICE_ADDRESS): str,
    }
)
async def websocket_notify_on_aldb_status(hass, connection, msg):
    """Tell Insteon a new ALDB record was added."""

    device = devices[msg[DEVICE_ADDRESS]]
    if not device:
        notify_device_not_found(connection, msg, INSTEON_DEVICE_NOT_FOUND)
        return

    @callback
    def record_added(controller, responder, group):
        """Forward ALDB events to websocket."""
        forward_data = {"type": "record_loaded"}
        connection.send_message(websocket_api.event_message(msg["id"], forward_data))

    @callback
    def aldb_loaded():
        """Forward ALDB loaded event to websocket."""
        forward_data = {
            "type": "status_changed",
            "is_loading": device.aldb.status == ALDBStatus.LOADING,
        }
        connection.send_message(websocket_api.event_message(msg["id"], forward_data))

    @callback
    def async_cleanup() -> None:
        """Remove signal listeners."""
        unsubscribe_topic(record_added, f"{DEVICE_LINK_CONTROLLER_CREATED}.{device.id}")
        unsubscribe_topic(record_added, f"{DEVICE_LINK_RESPONDER_CREATED}.{device.id}")
        unsubscribe_topic(aldb_loaded, f"{device.id}.{ALDB_STATUS_CHANGED}")

        forward_data = {"type": "unsubscribed"}
        connection.send_message(websocket_api.event_message(msg["id"], forward_data))

    connection.subscriptions[msg["id"]] = async_cleanup
    subscribe_topic(record_added, f"{DEVICE_LINK_CONTROLLER_CREATED}.{device.id}")
    subscribe_topic(record_added, f"{DEVICE_LINK_RESPONDER_CREATED}.{device.id}")
    subscribe_topic(aldb_loaded, f"{device.id}.{ALDB_STATUS_CHANGED}")

    connection.send_result(msg[ID])


@callback
def async_load_api(hass):
    """Set up the web socket API."""
    websocket_api.async_register_command(hass, websocket_get_device)
    websocket_api.async_register_command(hass, websocket_get_aldb)
    websocket_api.async_register_command(hass, websocket_change_aldb_record)
    websocket_api.async_register_command(hass, websocket_create_aldb_record)
    websocket_api.async_register_command(hass, websocket_write_aldb)
    websocket_api.async_register_command(hass, websocket_load_aldb)
    websocket_api.async_register_command(hass, websocket_reset_aldb)
    websocket_api.async_register_command(hass, websocket_add_default_links)
    websocket_api.async_register_command(hass, websocket_notify_on_aldb_status)

    websocket_api.async_register_command(hass, websocket_get_properties)
    websocket_api.async_register_command(hass, websocket_change_properties_record)
    websocket_api.async_register_command(hass, websocket_write_properties)
    websocket_api.async_register_command(hass, websocket_load_properties)
    websocket_api.async_register_command(hass, websocket_reset_properties)
