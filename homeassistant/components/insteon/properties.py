"""Property update methods and schemas."""
from itertools import chain

from pyinsteon.constants import RAMP_RATES
from pyinsteon.device_types.device_base import Device
from pyinsteon.extended_property import (
    NON_TOGGLE_MASK,
    NON_TOGGLE_ON_OFF_MASK,
    OFF_MASK,
    ON_MASK,
    RAMP_RATE,
)
from pyinsteon.utils import ramp_rate_to_seconds, seconds_to_ramp_rate

TOGGLE = "Toggle on/off"
NON_TOGGLE_ON = "Non-Toggle On Only"
NON_TOGGLE_OFF = "Non-Toggle Off Only"
RADIO_BUTTON_GROUP_PROP = "radio_button_group_"
TOGGLE_PROP = "toggle_"

RAMP_RATE_SECONDS = list(dict.fromkeys(RAMP_RATES.values()))
RAMP_RATE_SECONDS.sort()

RAMP_RATE_SCHEMA = {
    "name": RAMP_RATE,
    "required": True,
    "type": "select",
    "options": RAMP_RATE_SECONDS,
}
BOOL_SCHEMA_BASE = {
    "required": True,
    "type": "boolean",
}
BYTE_SCHEMA_BASE = {
    "required": True,
    "type": "integer",
    "valueMin": 0,
    "valueMax": 255,
}
TOGGLE_SCHEMA_BASE = {
    "required": True,
    "type": "select",
    "options": [TOGGLE, NON_TOGGLE_ON, NON_TOGGLE_OFF],
}
TOGGLE_MODE = {TOGGLE: 0, NON_TOGGLE_ON: 1, NON_TOGGLE_OFF: 2}


def get_properties(device: Device):
    """Get the properties of an Insteon device and return the records and schema."""

    properties = []
    schema = {}

    # Limit the properties we manage at this time.
    for prop_name in device.operating_flags:
        if not device.operating_flags[prop_name].is_read_only:
            prop_dict, schema_dict = _get_property(device.operating_flags[prop_name])
            properties.append(prop_dict)
            schema[prop_name] = schema_dict

    mask_found = False
    for prop_name in device.properties:
        if device.properties[prop_name].is_read_only:
            continue

        if prop_name == RAMP_RATE:
            rr_prop, rr_schema = _get_ramp_rate_property(device.properties[prop_name])
            properties.append(rr_prop)
            schema[RAMP_RATE] = rr_schema

        elif not mask_found and "mask" in prop_name:
            mask_found = True
            toggle_props, toggle_schema = _get_toggle_properties(device)
            properties.extend(toggle_props)
            schema.update(toggle_schema)

            radio_button_props, radio_button_schema = _get_radio_button_properties(
                device
            )
            properties.extend(radio_button_props)
            schema.update(radio_button_schema)
        else:
            prop_dict, schema_dict = _get_property(device.properties[prop_name])
            properties.append(prop_dict)
            schema[prop_name] = schema_dict

    return properties, schema


def set_property(device, prop_name: str, value):
    """Update a property value."""
    if isinstance(value, bool) and prop_name in device.operating_flags:
        device.operating_flags[prop_name].new_value = value

    elif prop_name == RAMP_RATE:
        device.properties[prop_name].new_value = seconds_to_ramp_rate(value)

    elif prop_name.startswith(RADIO_BUTTON_GROUP_PROP):
        group = []

        existing_groups = _calc_radio_button_groups(device)
        curr_group = int(prop_name[-1])
        curr_buttons = (
            existing_groups[curr_group] if len(existing_groups) > curr_group else []
        )

        # reset the definitions of any buttons in the current radio button group
        for button in curr_buttons:
            button_str = f"_{button}" if button != 1 else ""
            on_name = f"{ON_MASK}{button_str}"
            off_name = f"{OFF_MASK}{button_str}"
            device.properties[on_name].new_value = 0
            device.properties[off_name].new_value = 0

        # Map button names to button numbers
        buttons = {device.groups[button].name: button for button in device.groups}
        for button_name in value:
            group.append(buttons[button_name])

        # A group must have more than one button
        if len(group) > 1:
            device.set_radio_buttons(group)

    elif prop_name.startswith(TOGGLE_PROP):
        button_name = prop_name[len(TOGGLE_PROP) :]
        for button in device.groups:
            if device.groups[button].name == button_name:
                device.set_toggle_mode(button, TOGGLE_MODE[value])

    else:
        device.properties[prop_name].new_value = value


def _get_property(prop):
    """Return a property data row."""
    value, modified = _get_usable_value(prop)
    prop_dict = {"name": prop.name, "value": value, "modified": modified}
    schema = BOOL_SCHEMA_BASE if isinstance(prop.value, bool) else BYTE_SCHEMA_BASE
    return prop_dict, {"name": prop.name, **schema}


def _get_toggle_properties(device):
    """Generate the mask properties for a KPL device."""
    props = []
    schema = {}
    toggle_prop = device.properties[NON_TOGGLE_MASK]
    toggle_on_prop = device.properties[NON_TOGGLE_ON_OFF_MASK]
    for button in device.groups:
        name = f"{TOGGLE_PROP}{device.groups[button].name}"
        value, modified = _toggle_button_value(toggle_prop, toggle_on_prop, button)
        props.append({"name": name, "value": value, "modified": modified})
        schema[name] = {"name": name, **TOGGLE_SCHEMA_BASE}
    return props, schema


def _toggle_button_value(non_toggle_prop, toggle_on_prop, button):
    """Determine the toggle value of a button."""
    toggle_mask, toggle_modified = _get_usable_value(non_toggle_prop)
    toggle_on_mask, toggle_on_modified = _get_usable_value(toggle_on_prop)

    bit = button - 1
    if not toggle_mask & 1 << bit:
        value = TOGGLE
    else:
        if toggle_on_mask & 1 << bit:
            value = NON_TOGGLE_ON
        else:
            value = NON_TOGGLE_OFF

    modified = False
    if toggle_modified:
        curr_bit = non_toggle_prop.value & 1 << bit
        new_bit = non_toggle_prop.new_value & 1 << bit
        modified = not curr_bit == new_bit

    if not modified and value != TOGGLE and toggle_on_modified:
        curr_bit = toggle_on_prop.value & 1 << bit
        new_bit = toggle_on_prop.new_value & 1 << bit
        modified = not curr_bit == new_bit

    return value, modified


def _get_radio_button_properties(device):
    """Return the values and schema to set KPL buttons as radio buttons."""
    rb_groups = _calc_radio_button_groups(device)
    props = []
    schema = {}
    index = 0
    remaining_buttons = []

    buttons_in_groups = [button for button in chain.from_iterable(rb_groups)]

    # Identify buttons not belonging to any group
    for button in device.groups:
        if button not in buttons_in_groups:
            remaining_buttons.append(button)

    for rb_group in rb_groups:
        name = f"{RADIO_BUTTON_GROUP_PROP}{index}"
        button_names = [device.groups[button].name for button in rb_group]
        button_1 = rb_group[0]
        button_str = f"_{button_1}" if button_1 != 1 else ""
        on_mask = device.properties[f"{ON_MASK}{button_str}"]
        off_mask = device.properties[f"{OFF_MASK}{button_str}"]
        modified = on_mask.is_dirty or off_mask.is_dirty
        props.append(
            {
                "name": name,
                "modified": modified,
                "value": button_names,
            }
        )
        selections = [
            button for button in chain.from_iterable([rb_group, remaining_buttons])
        ]
        selections.sort()
        schema[name] = {
            "name": name,
            "required": False,
            "type": "multi_select",
            "options": [device.groups[button].name for button in selections],
        }
        index += 1

    if len(remaining_buttons) > 1:
        name = f"{RADIO_BUTTON_GROUP_PROP}{index}"
        props.append(
            {
                "name": name,
                "modified": False,
                "value": [],
            }
        )
        schema[name] = {
            "name": name,
            "required": False,
            "type": "multi_select",
            "options": [device.groups[button].name for button in remaining_buttons],
        }

    return props, schema


def _calc_radio_button_groups(device):
    """Return existing radio button groups."""
    rb_groups = []
    for button in device.groups:
        if button not in [b for b in chain.from_iterable(rb_groups)]:
            button_str = "" if button == 1 else f"_{button}"
            on_mask, _ = _get_usable_value(device.properties[f"{ON_MASK}{button_str}"])
            if on_mask != 0:
                rb_group = [button]
                for bit in list(range(0, button - 1)) + list(range(button, 8)):
                    if on_mask & 1 << bit:
                        rb_group.append(bit + 1)
                if len(rb_group) > 1:
                    rb_groups.append(rb_group)
    return rb_groups


def _get_ramp_rate_property(prop):
    """Return the value and schema of a ramp rate property."""
    rr_prop, _ = _get_property(prop)
    rr_prop["value"] = ramp_rate_to_seconds(rr_prop["value"])
    return rr_prop, RAMP_RATE_SCHEMA


def _get_usable_value(prop):
    """Return the current or the modified value of a property."""
    value = prop.value if prop.new_value is None else prop.new_value
    return value, prop.is_dirty
