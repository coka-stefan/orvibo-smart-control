import logging
import asyncio
from datetime import timedelta
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_FAMILY_ID,
    CONF_LOCK_USER_NAMES,
    CONF_LOCK_SNAPSHOT_LIMIT,
    DEFAULT_LOCK_SNAPSHOT_LIMIT,
    CONF_TRANSPORT_MODE,
    CONF_PASSWORD_HASH,
    CONF_CLOUD_REGION,
    CONF_USE_INDEPENDENT_LAN_CREDENTIALS,
    CONF_LAN_USERNAME,
    CONF_LAN_PASSWORD_HASH,
    CONF_POLL_INTERVAL_MINUTES,
    CONF_AVAILABILITY_NOTIFICATIONS,
    CONF_NOTIFY_ONLINE,
    CONF_NOTIFY_OFFLINE,
    CONF_NOTIFY_SERVICE,
    CONF_UPDATE_CHECK_ENABLED,
    CONF_UPDATE_CHECK_INTERVAL_HOURS,
    DEFAULT_POLL_INTERVAL_MINUTES,
    MIN_POLL_INTERVAL_MINUTES,
    MAX_POLL_INTERVAL_MINUTES,
    DEFAULT_UPDATE_CHECK_INTERVAL_HOURS,
    MIN_UPDATE_CHECK_INTERVAL_HOURS,
    MAX_UPDATE_CHECK_INTERVAL_HOURS,
)
from .capabilities import TransportMode
from .protocol import migrate_password_credentials
from .models import AccountCredentials
from .cloud import cloud_for_region
from .coordinator import OrviboSmartControlCoordinator
from .selection import CONF_DEVICE_AREAS, selected_device_ids
from .service_handlers import async_register_services
from .meari_probe import async_cancel_video_probes
from .runtime_options import AvailabilityNotifier, IntegrationUpdateChecker
from .registry_sync import assign_room_areas, sync_selected_device_registries
from .frontend_resources import async_register_card_resources

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ("switch", "light", "cover", "sensor", "binary_sensor", "climate", "fan", "camera")

# This integration is configured through config entries and does not read configuration.yaml.
# Newer HA versions require the domain argument for empty_config_schema.
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Replace legacy plaintext passwords with replayable protocol digests."""
    if entry.version > 3:
        return False
    try:
        migrated_data = migrate_password_credentials(entry.data)
    except ValueError:
        _LOGGER.error("Config entry is missing migratable ORVIBO login credentials")
        return False
    if entry.version < 3 or migrated_data != dict(entry.data):
        hass.config_entries.async_update_entry(
            entry,
            data=migrated_data,
            version=3,
        )
    return True


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up services."""
    await async_register_card_resources(hass)
    await async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    username = entry.data[CONF_USERNAME]
    password_hash = entry.data[CONF_PASSWORD_HASH]
    family_id = entry.data.get(CONF_FAMILY_ID)
    options = entry.options
    try:
        transport_mode = TransportMode(
            options.get(CONF_TRANSPORT_MODE, TransportMode.AUTO.value)
        )
    except ValueError:
        transport_mode = TransportMode.AUTO
    try:
        poll_minutes = int(
            options.get(
                CONF_POLL_INTERVAL_MINUTES,
                DEFAULT_POLL_INTERVAL_MINUTES,
            )
        )
    except (TypeError, ValueError):
        poll_minutes = DEFAULT_POLL_INTERVAL_MINUTES
    poll_minutes = max(
        MIN_POLL_INTERVAL_MINUTES,
        min(MAX_POLL_INTERVAL_MINUTES, poll_minutes),
    )

    lan_credentials = None
    if options.get(CONF_USE_INDEPENDENT_LAN_CREDENTIALS, False):
        lan_credentials = AccountCredentials(
            username=str(options.get(CONF_LAN_USERNAME, "")),
            password_hash=str(options.get(CONF_LAN_PASSWORD_HASH, "")),
            family_id=str(family_id or ""),
        )

    coordinator = OrviboSmartControlCoordinator(
        hass,
        AccountCredentials(
            username=username,
            password_hash=password_hash,
            family_id=str(family_id or ""),
        ),
        lock_user_names=options.get(CONF_LOCK_USER_NAMES),
        lock_snapshot_limit=options.get(CONF_LOCK_SNAPSHOT_LIMIT, DEFAULT_LOCK_SNAPSHOT_LIMIT),
        cloud=cloud_for_region(entry.data.get(CONF_CLOUD_REGION)),
        transport_mode=transport_mode,
        lan_credentials=lan_credentials,
        poll_interval=timedelta(minutes=poll_minutes),
    )

    try:
        _LOGGER.info("Setting up Orvibo Mesh...")
        await coordinator._async_setup()
        _LOGGER.info("Coordinator setup complete")
    except ConfigEntryAuthFailed:
        raise
    except Exception as e:
        _LOGGER.error(f"Coordinator setup failed: {e}", exc_info=True)
        raise ConfigEntryNotReady from e

    detected_region = coordinator.https_client.cloud.region.value
    if entry.data.get(CONF_CLOUD_REGION) != detected_region:
        updated_data = dict(entry.data)
        updated_data[CONF_CLOUD_REGION] = detected_region
        hass.config_entries.async_update_entry(entry, data=updated_data)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    _LOGGER.info("Coordinator registered in hass.data")

    selected = selected_device_ids(options, coordinator.devices)
    if options.get(CONF_AVAILABILITY_NOTIFICATIONS, False):
        availability_notifier = AvailabilityNotifier(
            hass,
            entry.entry_id,
            coordinator.devices,
            coordinator.device_states,
            set(selected),
            notify_online=bool(options.get(CONF_NOTIFY_ONLINE, True)),
            notify_offline=bool(options.get(CONF_NOTIFY_OFFLINE, True)),
            notify_service=str(options.get(CONF_NOTIFY_SERVICE) or ""),
        )
        entry.async_on_unload(
            coordinator.async_add_listener(availability_notifier.process)
        )

    if options.get(CONF_UPDATE_CHECK_ENABLED, False):
        try:
            update_check_hours = int(
                options.get(
                    CONF_UPDATE_CHECK_INTERVAL_HOURS,
                    DEFAULT_UPDATE_CHECK_INTERVAL_HOURS,
                )
            )
        except (TypeError, ValueError):
            update_check_hours = DEFAULT_UPDATE_CHECK_INTERVAL_HOURS
        update_check_hours = max(
            MIN_UPDATE_CHECK_INTERVAL_HOURS,
            min(MAX_UPDATE_CHECK_INTERVAL_HOURS, update_check_hours),
        )
        update_checker = IntegrationUpdateChecker(
            hass,
            interval_hours=update_check_hours,
        )
        update_task = hass.async_create_background_task(
            update_checker.run(),
            name=f"{DOMAIN}_update_check",
        )
        entry.async_on_unload(update_task.cancel)

    # Automatically clean up history: retain seven days, run weekly, and cancel the task on unload
    coordinator.start_history_cleanup()
    entry.async_on_unload(coordinator.stop_history_cleanup)
    coordinator.start_temp_password_cleanup()
    entry.async_on_unload(coordinator.stop_temp_password_cleanup)

    # Load all platforms at once with async_forward_entry_setups
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    removed_registry_devices = sync_selected_device_registries(
        hass, entry, coordinator.devices
    )
    if removed_registry_devices:
        _LOGGER.info(
            "Removed %s unselected devices from the Home Assistant registry",
            removed_registry_devices,
        )

    async def _apply_after_refresh():
        """Wait for the coordinator's first refresh before applying area mappings."""
        if not coordinator.last_update_success:
            await coordinator.async_refresh()
        await _async_assign_areas(hass, entry)
        await _apply_device_areas(hass, entry)
    
    area_task = hass.async_create_task(_apply_after_refresh())
    entry.async_on_unload(area_task.cancel)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info("Orvibo Mesh setup complete")
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Reapply area mappings when the config entry is updated."""
    _LOGGER.info("Config entry updated; reapplying device area mappings")
    await _async_assign_areas(hass, entry)
    await _apply_device_areas(hass, entry)
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_assign_areas(hass: HomeAssistant, entry: ConfigEntry):
    """Map ORVIBO cloud rooms to Home Assistant areas for devices without one."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not coordinator:
        return
    assign_room_areas(hass, entry, coordinator.devices)


async def _apply_device_areas(hass: HomeAssistant, entry: ConfigEntry):
    """Apply configured area mappings to the HA device registry."""
    device_areas = entry.options.get(CONF_DEVICE_AREAS, {})
    if not device_areas:
        _LOGGER.debug("No device area mappings configured")
        return

    _LOGGER.debug(f"Applying device area mappings: {device_areas}")
    
    device_registry = dr.async_get(hass)
    
    for device_id, area_id in device_areas.items():
        if not area_id:
            continue
        
        device = device_registry.async_get_device(identifiers={(DOMAIN, device_id)})
        if device:
            _LOGGER.info(f"Setting area for device {device_id} to {area_id}")
            device_registry.async_update_device(
                device.id,
                area_id=area_id,
            )
        else:
            _LOGGER.warning(f"Device not found: {device_id}")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.info("Unloading Orvibo Mesh...")
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _LOGGER.info(f"Unload result: {unload_ok}")

    if unload_ok:
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator:
            await async_cancel_video_probes(coordinator)
            await coordinator.async_cleanup()
            _LOGGER.info("Coordinator cleanup complete")
        hass_data = hass.data.get(DOMAIN, {})
        hass_data.pop(entry.entry_id, None)
        _LOGGER.info("Removed from hass.data")

    return unload_ok
