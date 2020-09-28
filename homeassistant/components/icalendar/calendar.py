"""Support for iCalendar."""
import copy
from datetime import datetime, timedelta
import logging
import re

import icalendar
import recurring_ical_events
import requests
from requests.auth import HTTPBasicAuth
import voluptuous as vol

from homeassistant.components.calendar import (
    ENTITY_ID_FORMAT,
    PLATFORM_SCHEMA,
    CalendarEventDevice,
    calculate_offset,
    get_date,
    is_offset_reached,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.util import Throttle, dt

_LOGGER = logging.getLogger(__name__)

CONF_SEARCH = "search"
CONF_DAYS = "days"

OFFSET = "!!"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        # pylint: disable=no-value-for-parameter
        vol.Required(CONF_URL): vol.Url(),
        vol.Required(CONF_NAME): cv.string,
        vol.Inclusive(CONF_USERNAME, "authentication"): cv.string,
        vol.Inclusive(CONF_PASSWORD, "authentication"): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=True): cv.boolean,
        vol.Optional(CONF_DAYS, default=7): cv.positive_int,
        vol.Optional(CONF_SEARCH, default=".*"): cv.string,
    }
)

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=15)


def setup_platform(hass, config, add_entities, disc_info=None):
    """Set up the iCalendar platform."""
    url = config.get(CONF_URL)
    name = config.get(CONF_NAME)
    days = config.get(CONF_DAYS)
    search = config.get(CONF_SEARCH)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)

    entities = []

    entity_id = generate_entity_id(ENTITY_ID_FORMAT, name, hass=hass)
    entity = ICalendarCalendarEventDevice(
        name, url, username, password, entity_id, days, search
    )
    entities.append(entity)

    add_entities(entities, True)


class ICalendarCalendarEventDevice(CalendarEventDevice):
    """A device for getting the next Task from a iCalendar."""

    def __init__(
        self, name, url, username, password, entity_id, days, search, all_day=False
    ):
        """Create the WebDav Calendar Event Device."""
        self.data = ICalendarCalendarData(
            url, username, password, days, all_day, search
        )
        self.entity_id = entity_id
        self._event = None
        self._name = name
        self._offset_reached = False

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        return {"offset_reached": self._offset_reached}

    @property
    def event(self):
        """Return the next upcoming event."""
        return self._event

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    async def async_get_events(self, hass, start_date, end_date):
        """Get all events in a specific time frame."""
        return await self.data.async_get_events(hass, start_date, end_date)

    def update(self):
        """Update event data."""
        self.data.update()
        event = copy.deepcopy(self.data.event)
        if event is None:
            self._event = event
            return
        event = calculate_offset(event, OFFSET)
        self._offset_reached = is_offset_reached(event)
        self._event = event


class ICalendarCalendarData:
    """Class to utilize the iCalendar client object to get next event."""

    def __init__(self, url, username, password, days, include_all_day, search):
        """Set up how we are going to search the WebDav calendar."""
        self.url = url
        if username and password:
            self.auth = HTTPBasicAuth(username, password)
        else:
            self.auth = None

        self.days = days
        self.include_all_day = include_all_day
        self.search = search
        self.event = None

    async def async_get_events(self, hass, start_date, end_date):
        """Get all events in a specific time frame."""
        # Get event list from the current calendar
        events = await hass.async_add_job(
            self.icalendar_get_events, start_date, end_date
        )

        event_list = []
        for event in events:
            uid = None
            if "UID" in event:
                uid = event.get("UID")
            data = {
                "uid": uid,
                "summary": event.get("SUMMARY"),
                "start": self.get_hass_date(event.get("DTSTART").dt),
                "end": self.get_hass_date(self.get_end_date(event)),
                "location": self.get_attr_value(event, "LOCATION"),
                "description": self.get_attr_value(event, "DESCRIPTION"),
            }

            data["start"] = get_date(data["start"]).isoformat()
            data["end"] = get_date(data["end"]).isoformat()

            event_list.append(data)

        return event_list

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data."""
        start_date = dt.dt.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_date = start_date + dt.dt.timedelta(days=self.days)

        events = self.icalendar_get_events(start_date, end_date)

        # sort events by start date
        events.sort(key=lambda x: self.to_datetime(x["DTSTART"].dt))

        event = next(
            (
                event
                for event in events
                if (
                    self.is_matching(event, self.search)
                    and (not self.is_all_day(event) or self.include_all_day)
                    and not self.is_over(event)
                )
            ),
            None,
        )

        # If no matching event could be found
        if event is None:
            _LOGGER.debug("No matching event found in the %d results", len(events))
            self.event = None
            return

        # Populate the entity attributes with the event values
        self.event = {
            "summary": event.get("SUMMARY"),
            "start": self.get_hass_date(event.get("DTSTART").dt),
            "end": self.get_hass_date(self.get_end_date(event)),
            "location": self.get_attr_value(event, "LOCATION"),
            "description": self.get_attr_value(event, "DESCRIPTION"),
        }

    def icalendar_get_events(self, start_date, end_date):
        """Download and parse ics file."""
        calendar = icalendar.Calendar.from_ical(
            requests.get(self.url, auth=self.auth).text
        )
        return recurring_ical_events.of(calendar).between(
            start_date.replace(tzinfo=None), end_date.replace(tzinfo=None)
        )

    @staticmethod
    def is_matching(event, search):
        """Return if the event matches the filter criteria."""
        if search is None:
            return True

        pattern = re.compile(search)
        return (
            "SUMMARY" in event
            and pattern.match(event.get("SUMMARY"))
            or "LOCATION" in event
            and pattern.match(event.get("LOCATION"))
            or "DESCRIPTION" in event
            and pattern.match(event.get("DESCRIPTION"))
        )

    @staticmethod
    def is_all_day(event):
        """Return if the event last the whole day."""
        return not isinstance(event.get("DTSTART").dt, datetime)

    @staticmethod
    def is_over(event):
        """Return if the event is over."""
        return dt.now() >= ICalendarCalendarData.to_datetime(
            ICalendarCalendarData.get_end_date(event)
        )

    @staticmethod
    def get_hass_date(obj):
        """Return if the event matches."""
        if isinstance(obj, datetime):
            return {"dateTime": obj.isoformat()}

        return {"date": obj.isoformat()}

    @staticmethod
    def to_datetime(obj):
        """Return a datetime."""
        if isinstance(obj, datetime):
            if obj.tzinfo is None:
                # floating value, not bound to any time zone in particular
                # represent same time regardless of which time zone is currently being observed
                return obj.replace(tzinfo=dt.DEFAULT_TIME_ZONE)
            return obj
        return dt.as_local(dt.dt.datetime.combine(obj, dt.dt.time.min))

    @staticmethod
    def get_attr_value(obj, attribute):
        """Return the value of the attribute if defined."""
        if attribute in obj:
            return obj.get(attribute)
        return None

    @staticmethod
    def get_end_date(obj):
        """Return the end datetime as determined by dtend or duration."""
        if "DTEND" in obj:
            enddate = obj.get("DTEND").dt

        elif "DURATION" in obj:
            enddate = obj.get("DTSTART").dt + obj.get("DURATION").dt

        else:
            enddate = obj.get("DTSTART").dt + timedelta(days=1)

        return enddate
