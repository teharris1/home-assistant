"""Mock devices object to test Insteon."""
from unittest.mock import AsyncMock, MagicMock

from pyinsteon.address import Address
from pyinsteon.constants import ALDBStatus
from pyinsteon.device_types import (
    DimmableLightingControl_KeypadLinc_8,
    GeneralController,
    Hub,
    SwitchedLightingControl_SwitchLinc,
)
from pyinsteon.managers.saved_devices_manager import dict_to_aldb_record


class MockSwitchLinc(SwitchedLightingControl_SwitchLinc):
    """Mock SwitchLinc device."""

    @property
    def operating_flags(self):
        """Return no operating flags to force properties to be checked."""
        return {}


class MockDevices:
    """Mock devices class."""

    def __init__(self, connected=True):
        """Init the MockDevices class."""
        self._devices = {}
        self.modem = None
        self._connected = connected
        self.async_save = AsyncMock()
        self.add_x10_device = MagicMock()
        self.set_id = MagicMock()

    def __getitem__(self, address):
        """Return a a device from the device address."""
        return self._devices.get(Address(address))

    def __iter__(self):
        """Return an iterator of device addresses."""
        yield from self._devices

    def __len__(self):
        """Return the number of devices."""
        return len(self._devices)

    def get(self, address):
        """Return a device from an address or None if not found."""
        return self._devices.get(Address(address))

    async def async_load(self, *args, **kwargs):
        """Load the mock devices."""
        if self._connected:
            addr0 = Address("AA.AA.AA")
            addr1 = Address("11.11.11")
            addr2 = Address("22.22.22")
            addr3 = Address("33.33.33")
            self._devices[addr0] = Hub(addr0, 0x03, 0x00, 0x00, "Hub AA.AA.AA", "0")
            self._devices[addr1] = MockSwitchLinc(
                addr1, 0x02, 0x00, 0x00, "Device 11.11.11", "1"
            )
            self._devices[addr2] = GeneralController(
                addr2, 0x00, 0x00, 0x00, "Device 22.22.22", "2"
            )
            self._devices[addr3] = DimmableLightingControl_KeypadLinc_8(
                addr3, 0x02, 0x00, 0x00, "Device 33.33.33", "3"
            )

            for device in [self._devices[addr] for addr in [addr1, addr2, addr3]]:
                device.async_read_config = AsyncMock()
                device.aldb.async_write = AsyncMock()
                device.aldb.async_load = AsyncMock()
                device.async_add_default_links = AsyncMock()
                device.async_read_op_flags = AsyncMock()
                device.async_read_ext_properties = AsyncMock()
                device.async_write_op_flags = AsyncMock()
                device.async_write_ext_properties = AsyncMock()

            for device in [self._devices[addr] for addr in [addr2, addr3]]:
                device.async_status = AsyncMock()
            self._devices[addr1].async_status = AsyncMock(side_effect=AttributeError)
            self._devices[addr0].aldb.async_load = AsyncMock()
            self.modem = self._devices[addr0]

    def fill_aldb(self, address, records):
        """Fill the All-Link Database for a device."""
        device = self._devices[Address(address)]
        aldb_records = dict_to_aldb_record(records)

        device.aldb.load_saved_records(ALDBStatus.LOADED, aldb_records)

    def fill_properties(self, address, props_dict):
        """Fill the operating flags and extended properties of a device."""
        device = self._devices[Address(address)]
        operating_flags = props_dict.get("operating_flags", {})
        properties = props_dict.get("properties", {})

        for flag in operating_flags:
            value = operating_flags[flag]
            if device.operating_flags.get(flag):
                device.operating_flags[flag].load(value)
        for flag in properties:
            value = properties[flag]
            if device.properties.get(flag):
                device.properties[flag].load(value)
