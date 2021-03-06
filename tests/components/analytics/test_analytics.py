"""The tests for the analytics ."""
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from homeassistant.components.analytics.analytics import Analytics
from homeassistant.components.analytics.const import (
    ANALYTICS_ENDPOINT_URL,
    ATTR_BASE,
    ATTR_DIAGNOSTICS,
    ATTR_PREFERENCES,
    ATTR_STATISTICS,
    ATTR_USAGE,
)
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.loader import IntegrationNotFound

MOCK_HUUID = "abcdefg"


async def test_no_send(hass, caplog, aioclient_mock):
    """Test send when no prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)
    analytics = Analytics(hass)
    with patch(
        "homeassistant.components.hassio.is_hassio",
        side_effect=Mock(return_value=False),
    ), patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.load()
        assert not analytics.preferences[ATTR_BASE]

        await analytics.send_analytics()

    assert "Nothing to submit" in caplog.text
    assert len(aioclient_mock.mock_calls) == 0


async def test_load_with_supervisor_diagnostics(hass):
    """Test loading with a supervisor that has diagnostics enabled."""
    analytics = Analytics(hass)
    assert not analytics.preferences[ATTR_DIAGNOSTICS]
    with patch(
        "homeassistant.components.hassio.get_supervisor_info",
        side_effect=Mock(return_value={"diagnostics": True}),
    ), patch(
        "homeassistant.components.hassio.is_hassio",
        side_effect=Mock(return_value=True),
    ):
        await analytics.load()
    assert analytics.preferences[ATTR_DIAGNOSTICS]


async def test_load_with_supervisor_without_diagnostics(hass):
    """Test loading with a supervisor that has not diagnostics enabled."""
    analytics = Analytics(hass)
    analytics._data[ATTR_PREFERENCES][ATTR_DIAGNOSTICS] = True

    assert analytics.preferences[ATTR_DIAGNOSTICS]

    with patch(
        "homeassistant.components.hassio.get_supervisor_info",
        side_effect=Mock(return_value={"diagnostics": False}),
    ), patch(
        "homeassistant.components.hassio.is_hassio",
        side_effect=Mock(return_value=True),
    ):
        await analytics.load()

    assert not analytics.preferences[ATTR_DIAGNOSTICS]


async def test_failed_to_send(hass, caplog, aioclient_mock):
    """Test failed to send payload."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=400)
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True})
    assert analytics.preferences[ATTR_BASE]

    with patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.send_analytics()
    assert "Sending analytics failed with statuscode 400" in caplog.text


async def test_failed_to_send_raises(hass, caplog, aioclient_mock):
    """Test raises when failed to send payload."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, exc=aiohttp.ClientError())
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True})
    assert analytics.preferences[ATTR_BASE]

    with patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.send_analytics()
    assert "Error sending analytics" in caplog.text


async def test_send_base(hass, caplog, aioclient_mock):
    """Test send base prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True})
    assert analytics.preferences[ATTR_BASE]

    with patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.send_analytics()
    assert f"'huuid': '{MOCK_HUUID}'" in caplog.text
    assert f"'version': '{HA_VERSION}'" in caplog.text
    assert "'installation_type':" in caplog.text
    assert "'integration_count':" not in caplog.text
    assert "'integrations':" not in caplog.text


async def test_send_base_with_supervisor(hass, caplog, aioclient_mock):
    """Test send base prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)

    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True})
    assert analytics.preferences[ATTR_BASE]

    with patch(
        "homeassistant.components.hassio.get_supervisor_info",
        side_effect=Mock(return_value={"supported": True, "healthy": True}),
    ), patch(
        "homeassistant.components.hassio.get_info",
        side_effect=Mock(return_value={}),
    ), patch(
        "homeassistant.components.hassio.get_host_info",
        side_effect=Mock(return_value={}),
    ), patch(
        "homeassistant.components.hassio.is_hassio",
        side_effect=Mock(return_value=True),
    ), patch(
        "homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID
    ):
        await analytics.send_analytics()
    assert f"'huuid': '{MOCK_HUUID}'" in caplog.text
    assert f"'version': '{HA_VERSION}'" in caplog.text
    assert "'supervisor': {'healthy': True, 'supported': True}}" in caplog.text
    assert "'installation_type':" in caplog.text
    assert "'integration_count':" not in caplog.text
    assert "'integrations':" not in caplog.text


async def test_send_usage(hass, caplog, aioclient_mock):
    """Test send usage prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True, ATTR_USAGE: True})
    assert analytics.preferences[ATTR_BASE]
    assert analytics.preferences[ATTR_USAGE]
    hass.config.components = ["default_config"]

    with patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.send_analytics()
    assert "'integrations': ['default_config']" in caplog.text
    assert "'integration_count':" not in caplog.text


async def test_send_usage_with_supervisor(hass, caplog, aioclient_mock):
    """Test send usage with supervisor prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)

    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True, ATTR_USAGE: True})
    assert analytics.preferences[ATTR_BASE]
    assert analytics.preferences[ATTR_USAGE]
    hass.config.components = ["default_config"]

    with patch(
        "homeassistant.components.hassio.get_supervisor_info",
        side_effect=Mock(
            return_value={
                "healthy": True,
                "supported": True,
                "addons": [{"slug": "test_addon"}],
            }
        ),
    ), patch(
        "homeassistant.components.hassio.get_info",
        side_effect=Mock(return_value={}),
    ), patch(
        "homeassistant.components.hassio.get_host_info",
        side_effect=Mock(return_value={}),
    ), patch(
        "homeassistant.components.hassio.async_get_addon_info",
        side_effect=AsyncMock(
            return_value={
                "slug": "test_addon",
                "protected": True,
                "version": "1",
                "auto_update": False,
            }
        ),
    ), patch(
        "homeassistant.components.hassio.is_hassio",
        side_effect=Mock(return_value=True),
    ), patch(
        "homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID
    ):
        await analytics.send_analytics()
    assert (
        "'addons': [{'slug': 'test_addon', 'protected': True, 'version': '1', 'auto_update': False}]"
        in caplog.text
    )
    assert "'addon_count':" not in caplog.text


async def test_send_statistics(hass, caplog, aioclient_mock):
    """Test send statistics prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True, ATTR_STATISTICS: True})
    assert analytics.preferences[ATTR_BASE]
    assert analytics.preferences[ATTR_STATISTICS]
    hass.config.components = ["default_config"]

    with patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.send_analytics()
    assert (
        "'state_count': 0, 'automation_count': 0, 'integration_count': 1, 'user_count': 0"
        in caplog.text
    )
    assert "'integrations':" not in caplog.text


async def test_send_statistics_one_integration_fails(hass, caplog, aioclient_mock):
    """Test send statistics prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True, ATTR_STATISTICS: True})
    assert analytics.preferences[ATTR_BASE]
    assert analytics.preferences[ATTR_STATISTICS]
    hass.config.components = ["default_config"]

    with patch(
        "homeassistant.components.analytics.analytics.async_get_integration",
        side_effect=IntegrationNotFound("any"),
    ), patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.send_analytics()

    post_call = aioclient_mock.mock_calls[0]
    assert "huuid" in post_call[2]
    assert post_call[2]["integration_count"] == 0


async def test_send_statistics_async_get_integration_unknown_exception(
    hass, caplog, aioclient_mock
):
    """Test send statistics prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True, ATTR_STATISTICS: True})
    assert analytics.preferences[ATTR_BASE]
    assert analytics.preferences[ATTR_STATISTICS]
    hass.config.components = ["default_config"]

    with pytest.raises(ValueError), patch(
        "homeassistant.components.analytics.analytics.async_get_integration",
        side_effect=ValueError,
    ), patch("homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID):
        await analytics.send_analytics()


async def test_send_statistics_with_supervisor(hass, caplog, aioclient_mock):
    """Test send statistics prefrences are defined."""
    aioclient_mock.post(ANALYTICS_ENDPOINT_URL, status=200)
    analytics = Analytics(hass)
    await analytics.save_preferences({ATTR_BASE: True, ATTR_STATISTICS: True})
    assert analytics.preferences[ATTR_BASE]
    assert analytics.preferences[ATTR_STATISTICS]

    with patch(
        "homeassistant.components.hassio.get_supervisor_info",
        side_effect=Mock(
            return_value={
                "healthy": True,
                "supported": True,
                "addons": [{"slug": "test_addon"}],
            }
        ),
    ), patch(
        "homeassistant.components.hassio.get_info",
        side_effect=Mock(return_value={}),
    ), patch(
        "homeassistant.components.hassio.get_host_info",
        side_effect=Mock(return_value={}),
    ), patch(
        "homeassistant.components.hassio.async_get_addon_info",
        side_effect=AsyncMock(
            return_value={
                "slug": "test_addon",
                "protected": True,
                "version": "1",
                "auto_update": False,
            }
        ),
    ), patch(
        "homeassistant.components.hassio.is_hassio",
        side_effect=Mock(return_value=True),
    ), patch(
        "homeassistant.helpers.instance_id.async_get", return_value=MOCK_HUUID
    ):
        await analytics.send_analytics()
    assert "'addon_count': 1" in caplog.text
    assert "'integrations':" not in caplog.text
