# NRW Flood

[![Test](https://github.com/proffalken/ha-nrw-flood/actions/workflows/test.yml/badge.svg)](https://github.com/proffalken/ha-nrw-flood/actions/workflows/test.yml)
[![Validate](https://github.com/proffalken/ha-nrw-flood/actions/workflows/validate.yml/badge.svg)](https://github.com/proffalken/ha-nrw-flood/actions/workflows/validate.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for flood data from
[Natural Resources Wales (NRW)](https://naturalresources.wales/flooding/):

- **Flood warnings and alerts** in force in the flood areas you choose
- **River levels** at the monitoring stations you choose, with rate of change
  and trend
- The Wales-wide **5-day flood risk forecast**

It works anywhere in Wales. You set a location and a search radius, then pick
from the flood areas and river level stations near that location.

> [!WARNING]
> NRW states that its APIs carry no service level guarantee, must not be used
> for safety-critical applications, and do not replace NRW's own flood
> warning service. Sign up to
> [NRW's flood warnings](https://naturalresources.wales/flooding/sign-up-to-receive-flood-warnings/)
> or call Floodline on 0345 988 1188. Use this integration alongside them, not
> instead of them.

## Requirements

- Home Assistant 2026.10 or later
- A free account on the [NRW API portal](https://api-portal.naturalresources.wales/)
  with a subscription to one or more of these products. Each product issues
  its own key, and a key for one product is rejected by the others:

  | API portal product                                          | Gives you                  |
  | ----------------------------------------------------------- | -------------------------- |
  | Open Data - Live Flood Warnings and Alerts API - Version 3  | Warning sensors and events |
  | Open Data - River level, Rainfall and Sea Data API          | River level sensors        |
  | Open Data - 5-day Flood Risk for Wales API                  | Forecast sensors           |

  You need at least one. Leave the others blank and their sensors are not
  created.

## Installation

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/proffalken/ha-nrw-flood` as an **Integration**.
2. Install **NRW Flood** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and choose
   **NRW Flood**.

## Configuration

1. **Keys and location.** Enter the key for each API you subscribed to. The
   location defaults to your Home Assistant home. The search radius sets
   which flood areas and stations are offered next.
2. **Flood areas** (warnings API only). Choose the flood alert and flood
   warning areas to watch. The list of areas comes from
   [DataMapWales](https://datamap.gov.wales/), which needs no key. If
   DataMapWales is unavailable you are asked to type the area codes instead,
   separated by commas. Each area's code is shown on its page on the NRW flood
   warnings service.
3. **River level stations** (river level API only). Choose the stations to
   track.

You can change the areas and stations later from the integration's
**Configure** button. Each location you set up is a separate entry.

## Entities

### NRW flood warnings

| Entity                                 | Description                                                                                                                                                                                  |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sensor.…_warning_level`               | Highest level in force in your areas: `none`, `alert`, `warning` or `severe`. The `warnings` attribute lists each one (code, description, level, message, times raised and changed, tidal). |
| `sensor.…_active_warnings`             | Number of warnings and alerts in force in your areas                                                                                                                                         |
| `binary_sensor.…_flood_alert`          | On when a flood alert **or higher** is in force                                                                                                                                              |
| `binary_sensor.…_flood_warning`        | On when a flood warning **or higher** is in force                                                                                                                                            |
| `binary_sensor.…_severe_flood_warning` | On when a severe flood warning is in force                                                                                                                                                   |

Polled every 5 minutes. Warnings that NRW marks as "no longer in force" are
ignored.

### One device per river level station

| Entity                    | Description                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------ |
| `sensor.…_level`          | Latest river level in metres. Attributes: station ID, station page URL, NRW status. |
| `sensor.…_rate_of_change` | Change over roughly the last hour, in metres per hour                               |
| `sensor.…_trend`          | `rising`, `steady` or `falling`, as reported by NRW                                  |
| `sensor.…_last_reading`   | Time of the latest reading                                                           |

Polled every 15 minutes, which is how often NRW takes readings. On startup the
integration loads each station's recent history once, so the rate of change is
available straight away rather than after an hour.

The levels are gauge readings in metres at that station. They are not depths
and are not comparable between stations. NRW describes the data as unverified.

### NRW flood risk forecast

| Entity                     | Description                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------------- |
| `sensor.…_forecast_issued` | When the current forecast was issued. Attributes: `summary` text and the 5 `days`.               |
| `sensor.…_areas_at_risk`   | Number of entries in NRW's areas-at-risk list. Attribute `areas` holds them as NRW returns them. |
| `image.…_flood_risk_map_day_1` … `_day_5` | NRW's risk map for each forecast day. Attribute `day` gives the date. |

The summary text covers the whole of Wales and doesn't name areas. The maps
are the only place NRW shows the risk area by area.

Polled every hour. The format of the areas-at-risk entries is not documented,
and the list was empty while this integration was written, so the entries are
passed through unchanged.

## Dashboard

The integration adds an **NRW Flood** dashboard type. To create the
dashboard:

1. Go to **Settings → Dashboards → Add dashboard** and choose **NRW Flood**.
2. Give it a URL, for example `nrw-flood`.

It builds itself from the integration's entities each time it opens, so
gauges you add later appear without editing it. It shows:

- the warnings in force, with NRW's full message
- one card per gauge with its level, whether it is rising, steady or
  falling, and its rate of change. If you set reference levels for the
  gauge, the card also says how far the river is below the next one (or
  which one it is above) and shows a gauge with coloured bands
- the Wales-wide 5-day forecast summary, with a small risk map for each day
- links to NRW, Floodline and each gauge's page

History graphs are off by default to keep the dashboard quick to read. Set
`show_graphs: true` to add one per gauge.

Its single view is at `/<dashboard URL>/flood`, which you can use as a
notification's click action:

```yaml
data:
  clickAction: /nrw-flood/flood   # Android
  url: /nrw-flood/flood           # iOS
```

### Options

Edit the dashboard's raw configuration (**⋮ → Raw configuration editor**) to
add options under `strategy`:

```yaml
strategy:
  type: custom:nrw-flood
  title: Flood                   # default "Flood"
  show_graphs: true              # level history graph per gauge, default false
  hours_to_show: 48              # history graph length, default 24
  entry_id: 01J...               # only show one NRW Flood location
  thresholds:                    # reference levels: distance to the next
    sensor.wye_at_monmouth_level: # one, and a gauge with coloured bands
      - value: 5.2
        label: Mayhill floods
      - value: 6.0
        label: Wye Bridge closed
  extra_gauges:                  # level sensors from other integrations,
    - entity: sensor.old_wye_bridge_stage   # shown after the NRW gauges
      name: Wye at Hereford      # optional, defaults to the sensor's name
      trend: sensor.old_wye_bridge_status   # optional trend or status sensor
      note: The peak usually reaches Monmouth 14 to 26 hours later.
  links:                         # extra links in the Links section
    - name: Our flood plan
      url: https://example.com/flood-plan
```

Reference levels under `thresholds` work for extra gauges too: key them by
the extra gauge's entity ID.

## Events

The integration fires `nrw_flood_warning_changed` when a warning in your areas
is issued, changes level or message, or is removed:

| Field             | Value                                              |
| ----------------- | -------------------------------------------------- |
| `change`          | `issued`, `updated` or `removed`                   |
| `code`            | NRW flood area code, for example `103FWF011a`      |
| `description`     | Flood area description                             |
| `level`           | `alert`, `warning` or `severe` (`null` if removed) |
| `previous_level`  | Level before the change (`null` if issued)         |
| `message`         | NRW's message (`null` if removed)                  |
| `config_entry_id` | The entry that fired it                            |

No events are fired for the first poll after Home Assistant starts, so a
restart does not re-announce warnings already in force.

## Example automations

Notify when any flood alert or warning is issued or changes:

```yaml
triggers:
  - trigger: event
    event_type: nrw_flood_warning_changed
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "Flood {{ trigger.event.data.level or 'warning removed' }}"
      message: >-
        {{ trigger.event.data.description }}:
        {{ trigger.event.data.message or 'No longer in force' }}
```

Notify when a river passes a level you care about:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.wye_at_monmouth_level
    above: 5.2
actions:
  - action: notify.mobile_app_your_phone
    data:
      message: "The Wye at Monmouth is above 5.2 m"
```

## Development

```shell
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
npm test   # dashboard strategy tests (Node's built-in runner, no dependencies)
```

`scripts/capture_fixtures.py` runs the client against the live APIs and prints
what it finds. With `--save` it writes any non-empty warnings or areas-at-risk
responses to `tests/fixtures/captured/` (git-ignored) for turning into test
fixtures. Keys are read from the `NRW_WARNINGS_KEY`, `NRW_LEVELS_KEY` and
`NRW_FORECAST_KEY` environment variables:

```shell
uv run python scripts/capture_fixtures.py 51.81 -2.71 15 --save
```

`tests/fixtures/warnings_active.json` is synthetic, because no warnings were
in force while it was written. Its field names and severity scale match other
open-source NRW v3 clients. It should be replaced with a real capture.

## Attribution

Contains Natural Resources Wales information © Natural Resources Wales and
Database Right. All rights Reserved. Used under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

## Licence

[MIT](LICENSE)
