"""Web socket API for Insteon devices."""
import logging

from pyinsteon import devices
import voluptuous as vol
import voluptuous_serialize

from homeassistant.components import websocket_api
from homeassistant.core import callback

from .const import DOMAIN
from .schemas import ALDB_SCHEMA

_LOGGER = logging.getLogger(__name__)
TYPE = "type"
ID = "id"
DEVICE_ID = "device_id"
ALDB_RECORD = "record"


async def async_get_devices(hass, connection, msg):
    """Get the HA and Insteon devices."""
    ha_device = await async_get_ha_device(hass, msg[DEVICE_ID])
    if not ha_device:
        notify_device_not_found(connection, msg, "HA device not found.")
        return None, None
    device = get_insteon_device(ha_device)
    if not device:
        notify_device_not_found(connection, msg, "Insteon device not found.")
        return ha_device, None
    return ha_device, device


def compute_device_name(ha_device):
    """Return the HA device name."""
    return ha_device.name_by_user if ha_device.name_by_user else ha_device.name


async def async_get_ha_device(hass, device_id):
    """Get the Insteon device from a device registry id."""
    dev_registry = await hass.helpers.device_registry.async_get_registry()
    return dev_registry.async_get(device_id)


def get_insteon_device(ha_device):
    """Return the Insteon device from an HA device."""
    for identifier in ha_device.identifiers:
        address = identifier[1]
    return devices[address]


async def async_get_device_name_from_address(dev_registry, address):
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


async def async_record_to_dict(hass, record):
    """Convert an ALDB record to a dict."""
    dev_registry = await hass.helpers.device_registry.async_get_registry()
    return {
        "mem_addr": record.mem_addr,
        "in_use": record.is_in_use,
        "mode": "C" if record.is_controller else "R",
        "highwater": record.is_high_water_mark,
        "group": record.group,
        "target": str(record.target),
        "target_name": await async_get_device_name_from_address(
            dev_registry, record.target
        ),
        "data1": record.data1,
        "data2": record.data2,
        "data3": record.data3,
        "dirty": False,
    }


async def async_get_aldb_records(hass, aldb):
    """Get all ALDB records and changes."""
    records = {
        mem_addr: await async_record_to_dict(hass, aldb[mem_addr]) for mem_addr in aldb
    }
    return await async_merge_pending_changes(hass, records, aldb.get_pending())


def notify_device_not_found(connection, msg, text):
    """Notify the caller that the device was not found."""
    connection.send_message(
        websocket_api.error_message(msg[ID], websocket_api.const.ERR_NOT_FOUND, text)
    )
    return


def default_link_to_dict(link):
    """Convert a default link to a dict."""
    return {
        "is_controller": link.is_controller,
        "group": link.group,
        "dev_data1": link.dev_data1,
        "dev_data2": link.dev_data2,
        "dev_data3": link.dev_data3,
        "modem_data1": link.modem_data1,
        "modem_data2": link.modem_data2,
        "modem_data3": link.modem_data3,
    }


async def async_reload_and_save_aldb(hass, device):
    """Add default links to an Insteon device."""
    await device.aldb.async_load(refresh=True)
    await devices.async_save(workdir=hass.config.config_dir)


async def async_merge_pending_changes(hass, aldb, changes):
    """Merge the ALDB records with pending changes."""
    next_new_id = -1
    for rec in changes:
        if rec.mem_addr == 0:
            rec.mem_addr = next_new_id
            next_new_id -= 1
        aldb[rec.mem_addr] = await async_record_to_dict(hass, rec)
        aldb[rec.mem_addr]["dirty"] = True
        _LOGGER.info("Record %d is dirty", rec.mem_addr)
    return aldb


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {vol.Required(TYPE): "insteon/device/get", vol.Required(DEVICE_ID): str}
)
async def websocket_get_device(hass, connection, msg):
    """Get an Insteon device."""
    ha_device, device = await async_get_devices(hass, connection, msg)
    if not ha_device or not device:
        return
    ha_name = compute_device_name(ha_device)
    device_info = {
        "name": ha_name,
        "address": str(device.address),
        "is_battery": device.is_battery,
        "aldb_status": str(device.aldb.status),
        "default_links": [default_link_to_dict(link) for link in device.default_links],
    }
    connection.send_result(msg[ID], device_info)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {vol.Required(TYPE): "insteon/aldb/get", vol.Required(DEVICE_ID): str}
)
async def websocket_get_aldb(hass, connection, msg):
    """Get the All-Link Database for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return

    records = await async_get_aldb_records(hass, device.aldb)

    aldb_info = {
        "schema": voluptuous_serialize.convert(
            ALDB_SCHEMA
        ),  # , custom_serializer=cv.voluptuous_serialize),
        "records": [v for v in records.values()],
    }
    for rec in aldb_info["records"]:
        if rec["dirty"]:
            _LOGGER.error("Record %d is being sent dirty", rec["mem_addr"])
    connection.send_result(msg[ID], aldb_info)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/change",
        vol.Required(DEVICE_ID): str,
        vol.Required(ALDB_RECORD): dict,
    }
)
async def websocket_change_aldb_record(hass, connection, msg):
    """Change an All-Link Database record for an Insteon device."""
    _LOGGER.info("Change started")
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
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


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/create",
        vol.Required(DEVICE_ID): str,
        vol.Required(ALDB_RECORD): dict,
    }
)
async def websocket_create_aldb_record(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
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


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/write",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_write_aldb(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return

    await device.aldb.async_write()
    hass.async_create_task(async_reload_and_save_aldb(hass, device))


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/load",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_load_aldb(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return

    hass.async_create_task(async_reload_and_save_aldb(hass, device))


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/reset",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_reset_aldb(hass, connection, msg):
    """Create an All-Link Database record for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return

    device.aldb.clear_pending()


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/aldb/add_default_links",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_add_default_links(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return

    device.aldb.clear_pending()
    await device.async_add_default_links()
    hass.async_create_task(async_reload_and_save_aldb(hass, device))


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/get",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_get_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/change",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_change_properties_record(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/write",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_write_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/load",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_load_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required(TYPE): "insteon/properties/reset",
        vol.Required(DEVICE_ID): str,
    }
)
async def websocket_reset_properties(hass, connection, msg):
    """Add the default All-Link Database records for an Insteon device."""
    _, device = await async_get_devices(hass, connection, msg)
    if not device:
        return


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

    websocket_api.async_register_command(hass, websocket_get_properties)
    websocket_api.async_register_command(hass, websocket_change_properties_record)
    websocket_api.async_register_command(hass, websocket_write_properties)
    websocket_api.async_register_command(hass, websocket_load_properties)
    websocket_api.async_register_command(hass, websocket_reset_properties)
