"""Tests for serving the dashboard strategy to the Home Assistant frontend."""

from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.setup import async_setup_component

from custom_components.nrw_flood.const import DOMAIN
from custom_components.nrw_flood.dashboard import STRATEGY_URL


async def test_strategy_file_is_served_and_loaded_on_every_page(hass, fake_frontend):
    assert await async_setup_component(hass, DOMAIN, {})

    (configs,) = fake_frontend.async_register_static_paths.await_args.args
    (config,) = configs
    assert config.url_path == STRATEGY_URL
    assert await hass.async_add_executor_job(Path(config.path).is_file)
    assert Path(config.path).name == "nrw-flood-strategy.js"

    urls = hass.data[DATA_EXTRA_MODULE_URL]
    assert len(urls) == 1
    (url,) = urls
    # Versioned, so browsers fetch the new file after an upgrade.
    assert url.startswith(f"{STRATEGY_URL}?v=")
    assert url.split("?v=")[1] not in ("", "None")


async def test_registered_once_with_several_entries(
    hass, fake_frontend, mock_config_entry, aioclient_mock
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from tests.test_init import _mock_all

    second = MockConfigEntry(
        domain=DOMAIN, data=dict(mock_config_entry.data), unique_id="other"
    )
    second.add_to_hass(hass)
    _mock_all(aioclient_mock)

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert fake_frontend.async_register_static_paths.await_count == 1
    assert len(hass.data[DATA_EXTRA_MODULE_URL]) == 1
