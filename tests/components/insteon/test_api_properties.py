"""Test the Insteon properties APIs."""

import json
from unittest.mock import patch

import pytest

from homeassistant.components import insteon
from homeassistant.components.insteon.api import async_load_api
from homeassistant.components.insteon.api.device import INSTEON_DEVICE_NOT_FOUND
from homeassistant.components.insteon.api.properties import (
    DEVICE_ADDRESS,
    ID,
    NON_TOGGLE_MASK,
    NON_TOGGLE_OFF_MODE,
    NON_TOGGLE_ON_MODE,
    NON_TOGGLE_ON_OFF_MASK,
    PROPERTY_NAME,
    PROPERTY_VALUE,
    RADIO_BUTTON_GROUP_PROP,
    TOGGLE_MODES,
    TOGGLE_ON_OFF_MODE,
    TOGGLE_PROP,
    TYPE,
    _get_radio_button_properties,
    _get_toggle_properties,
)

from .mock_devices import MockDevices

from tests.common import load_fixture


@pytest.fixture(name="properties_data", scope="session")
def aldb_data_fixture():
    """Load the controller state fixture data."""
    return json.loads(load_fixture("insteon/kpl_properties.json"))


async def _setup(hass, hass_ws_client, properties_data):
    """Set up tests."""
    ws_client = await hass_ws_client(hass)
    devices = MockDevices()
    await devices.async_load()
    devices.fill_properties("33.33.33", properties_data)
    async_load_api(hass)
    return ws_client, devices


async def test_get_properties(hass, hass_ws_client, properties_data):
    """Test getting an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {ID: 2, TYPE: "insteon/properties/get", DEVICE_ADDRESS: "33.33.33"}
        )
        msg = await ws_client.receive_json()
        assert msg["success"]
        assert len(msg["result"]["properties"]) == 54


async def test_change_operating_flag(hass, hass_ws_client, properties_data):
    """Test changing an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {
                ID: 2,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: "led_on",
                PROPERTY_VALUE: True,
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]
        # assert devices["33.33.33"].operating_flags["led_on"].new_value
        assert devices["33.33.33"].operating_flags["led_on"].is_dirty


async def test_change_property(hass, hass_ws_client, properties_data):
    """Test changing an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {
                ID: 2,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: "on_mask",
                PROPERTY_VALUE: 100,
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]
        assert devices["33.33.33"].properties["on_mask"].new_value == 100
        assert devices["33.33.33"].properties["on_mask"].is_dirty


async def test_change_ramp_rate_property(hass, hass_ws_client, properties_data):
    """Test changing an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {
                ID: 2,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: "ramp_rate",
                PROPERTY_VALUE: 4.5,
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]
        assert devices["33.33.33"].properties["ramp_rate"].new_value == 0x1A
        assert devices["33.33.33"].properties["ramp_rate"].is_dirty


async def test_change_radio_button_group(hass, hass_ws_client, properties_data):
    """Test changing an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)
    rb_props, schema = _get_radio_button_properties(devices["33.33.33"])

    # Make sure the baseline is correct
    assert rb_props[0]["name"] == f"{RADIO_BUTTON_GROUP_PROP}0"
    assert rb_props[0]["value"][0] == "on_off_switch_d"
    assert "dimmable_light_main" in schema[f"{RADIO_BUTTON_GROUP_PROP}0"]["options"]
    assert "dimmable_light_main" in schema[f"{RADIO_BUTTON_GROUP_PROP}1"]["options"]
    assert devices["33.33.33"].properties["on_mask"].value == 0
    assert devices["33.33.33"].properties["off_mask"].value == 0
    assert not devices["33.33.33"].properties["on_mask"].is_dirty
    assert not devices["33.33.33"].properties["off_mask"].is_dirty

    rb_props[0]["value"].append("dimmable_light_main")

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {
                ID: 2,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: f"{RADIO_BUTTON_GROUP_PROP}0",
                PROPERTY_VALUE: rb_props[0]["value"],
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]

        new_rb_props, new_schema = _get_radio_button_properties(devices["33.33.33"])
        assert "dimmable_light_main" in new_rb_props[0]["value"]
        assert (
            "dimmable_light_main"
            in new_schema[f"{RADIO_BUTTON_GROUP_PROP}0"]["options"]
        )
        assert (
            "dimmable_light_main"
            not in new_schema[f"{RADIO_BUTTON_GROUP_PROP}1"]["options"]
        )

        assert devices["33.33.33"].properties["on_mask"].new_value == 24
        assert devices["33.33.33"].properties["off_mask"].new_value == 24
        assert devices["33.33.33"].properties["on_mask"].is_dirty
        assert devices["33.33.33"].properties["off_mask"].is_dirty


async def test_create_radio_button_group(hass, hass_ws_client, properties_data):
    """Test changing an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)
    rb_props, schema = _get_radio_button_properties(devices["33.33.33"])

    # Make sure the baseline is correct
    assert len(rb_props) == 3

    rb_props[0]["value"].append("dimmable_light_main")

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {
                ID: 2,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: f"{RADIO_BUTTON_GROUP_PROP}2",
                PROPERTY_VALUE: ["dimmable_light_main", "on_off_switch_d"],
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]

        new_rb_props, new_schema = _get_radio_button_properties(devices["33.33.33"])
        assert len(rb_props) == 3
        assert "dimmable_light_main" in new_rb_props[0]["value"]
        assert (
            "dimmable_light_main"
            in new_schema[f"{RADIO_BUTTON_GROUP_PROP}0"]["options"]
        )
        assert (
            "dimmable_light_main"
            not in new_schema[f"{RADIO_BUTTON_GROUP_PROP}1"]["options"]
        )

        assert devices["33.33.33"].properties["on_mask"].new_value == 8
        assert devices["33.33.33"].properties["off_mask"].new_value == 8
        assert devices["33.33.33"].properties["on_mask"].is_dirty
        assert devices["33.33.33"].properties["off_mask"].is_dirty


async def test_change_toggle_property(hass, hass_ws_client, properties_data):
    """Update a button's toggle mode."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)
    device = devices["33.33.33"]
    toggle_props, _ = _get_toggle_properties(devices["33.33.33"])

    # Make sure the baseline is correct
    assert toggle_props[0]["name"] == f"{TOGGLE_PROP}{device.groups[1].name}"
    assert toggle_props[0]["value"] == TOGGLE_MODES[TOGGLE_ON_OFF_MODE]
    assert toggle_props[1]["value"] == TOGGLE_MODES[NON_TOGGLE_ON_MODE]
    assert device.properties[NON_TOGGLE_MASK].value == 2
    assert device.properties[NON_TOGGLE_ON_OFF_MASK].value == 2
    assert not device.properties[NON_TOGGLE_MASK].is_dirty
    assert not device.properties[NON_TOGGLE_ON_OFF_MASK].is_dirty

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {
                ID: 2,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: toggle_props[0]["name"],
                PROPERTY_VALUE: NON_TOGGLE_ON_MODE,
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]

        new_toggle_props, _ = _get_toggle_properties(devices["33.33.33"])
        assert new_toggle_props[0]["value"] == TOGGLE_MODES[NON_TOGGLE_ON_MODE]
        assert device.properties[NON_TOGGLE_MASK].new_value == 3
        assert device.properties[NON_TOGGLE_ON_OFF_MASK].new_value == 3
        assert device.properties[NON_TOGGLE_MASK].is_dirty
        assert device.properties[NON_TOGGLE_ON_OFF_MASK].is_dirty

        await ws_client.send_json(
            {
                ID: 3,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: toggle_props[0]["name"],
                PROPERTY_VALUE: NON_TOGGLE_OFF_MODE,
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]

        new_toggle_props, _ = _get_toggle_properties(devices["33.33.33"])
        assert new_toggle_props[0]["value"] == TOGGLE_MODES[NON_TOGGLE_OFF_MODE]
        assert device.properties[NON_TOGGLE_MASK].new_value == 3
        assert device.properties[NON_TOGGLE_ON_OFF_MASK].new_value is None
        assert device.properties[NON_TOGGLE_MASK].is_dirty
        assert not device.properties[NON_TOGGLE_ON_OFF_MASK].is_dirty

        await ws_client.send_json(
            {
                ID: 4,
                TYPE: "insteon/properties/change",
                DEVICE_ADDRESS: "33.33.33",
                PROPERTY_NAME: toggle_props[1]["name"],
                PROPERTY_VALUE: TOGGLE_ON_OFF_MODE,
            }
        )
        msg = await ws_client.receive_json()
        assert msg["success"]

        new_toggle_props, _ = _get_toggle_properties(devices["33.33.33"])
        assert new_toggle_props[1]["value"] == TOGGLE_MODES[TOGGLE_ON_OFF_MODE]
        assert device.properties[NON_TOGGLE_MASK].new_value == 0
        assert device.properties[NON_TOGGLE_ON_OFF_MASK].new_value == 0
        assert device.properties[NON_TOGGLE_MASK].is_dirty
        assert device.properties[NON_TOGGLE_ON_OFF_MASK].is_dirty


async def test_write_properties(hass, hass_ws_client, properties_data):
    """Test getting an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {ID: 2, TYPE: "insteon/properties/write", DEVICE_ADDRESS: "33.33.33"}
        )
        msg = await ws_client.receive_json()
        assert msg["success"]
        assert devices["33.33.33"].async_write_op_flags.call_count == 1
        assert devices["33.33.33"].async_write_ext_properties.call_count == 1


async def test_load_properties(hass, hass_ws_client, properties_data):
    """Test getting an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)

    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {ID: 2, TYPE: "insteon/properties/load", DEVICE_ADDRESS: "33.33.33"}
        )
        msg = await ws_client.receive_json()
        assert msg["success"]
        assert devices["33.33.33"].async_read_op_flags.call_count == 1
        assert devices["33.33.33"].async_read_ext_properties.call_count == 1


async def test_reset_properties(hass, hass_ws_client, properties_data):
    """Test getting an Insteon device's properties."""
    ws_client, devices = await _setup(hass, hass_ws_client, properties_data)

    device = devices["33.33.33"]
    device.operating_flags["led_on"].new_value = True
    device.properties["on_mask"].new_value = 100
    assert device.operating_flags["led_on"].is_dirty
    assert device.properties["on_mask"].is_dirty
    with patch.object(insteon.api.properties, "devices", devices):
        await ws_client.send_json(
            {ID: 2, TYPE: "insteon/properties/reset", DEVICE_ADDRESS: "33.33.33"}
        )
        msg = await ws_client.receive_json()
        assert msg["success"]
        assert not device.operating_flags["led_on"].is_dirty
        assert not device.properties["on_mask"].is_dirty


async def test_bad_address(hass, hass_ws_client, properties_data):
    """Test for a bad Insteon address."""
    ws_client, _ = await _setup(hass, hass_ws_client, properties_data)

    ws_id = 0
    for call in ["get", "write", "load", "reset"]:
        ws_id += 1
        await ws_client.send_json(
            {
                ID: ws_id,
                TYPE: f"insteon/properties/{call}",
                DEVICE_ADDRESS: "99.99.99",
            }
        )
        msg = await ws_client.receive_json()
        assert not msg["success"]
        assert msg["error"]["message"] == INSTEON_DEVICE_NOT_FOUND

    ws_id += 1
    await ws_client.send_json(
        {
            ID: ws_id,
            TYPE: "insteon/properties/change",
            DEVICE_ADDRESS: "99.99.99",
            PROPERTY_NAME: "led_on",
            PROPERTY_VALUE: True,
        }
    )
    msg = await ws_client.receive_json()
    assert not msg["success"]
    assert msg["error"]["message"] == INSTEON_DEVICE_NOT_FOUND
