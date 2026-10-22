// NRW Flood dashboard strategy.
//
// Served by the integration and loaded on every Home Assistant page. It adds
// an "NRW Flood" option to Settings > Dashboards > Add dashboard. The
// dashboard is rebuilt from the integration's entities each time it opens,
// so new gauges appear without editing anything.
//
// Optional strategy config (edit the dashboard's raw configuration):
//   title: Flood                 # dashboard and view title
//   hours_to_show: 24            # history graph length
//   entry_id: <config entry id>  # only show one NRW Flood location
//   thresholds:                  # reference levels, drawn as a gauge
//     sensor.wye_at_monmouth_level:
//       - value: 5.2
//         label: Mayhill floods
//   links:                       # extra links in the links section
//     - name: Emergency protocols
//       url: https://example.com

export const STRATEGY_TYPE = "nrw-flood";
const PLATFORM = "nrw_flood";
const VIEW_PATH = "flood";
const DEFAULT_TITLE = "Flood";
const DEFAULT_HOURS = 24;

const NRW_WARNINGS_URL = "https://naturalresources.wales/flooding/check-flood-warnings/";
const NRW_RIVERS_URL = "https://rivers-and-seas.naturalresources.wales/";

const TIME_FORMAT = "%a %-d %b, %H:%M";

function nrwEntities(hass, entryId) {
  const entities = Object.values(hass.entities || {}).filter((e) => e.platform === PLATFORM);
  if (!entryId) return entities;
  return entities.filter((e) => {
    const device = (hass.devices || {})[e.device_id];
    return device && (device.config_entries || []).includes(entryId);
  });
}

function byKey(entities, key) {
  return entities.find((e) => e.translation_key === key)?.entity_id;
}

function deviceName(hass, deviceId) {
  const device = (hass.devices || {})[deviceId] || {};
  return device.name_by_user || device.name || "River gauge";
}

function statusContent(levelId) {
  return `{% set level = states('${levelId}') %}
{% set ws = state_attr('${levelId}', 'warnings') or [] %}
{% set names = {'alert': 'Flood alert', 'warning': 'Flood warning', 'severe': 'SEVERE flood warning'} %}
{% if level in ['unknown', 'unavailable'] %}
<ha-alert alert-type="info">Flood warning data is unavailable right now. Check NRW directly.</ha-alert>
{% elif ws | count == 0 %}
<ha-alert alert-type="success">No flood alerts or warnings are in force in the watched areas.</ha-alert>
{% else %}
{% for w in ws %}
<ha-alert alert-type="{{ 'warning' if w.level == 'alert' else 'error' }}" title="{{ names.get(w.level, 'Flood warning') }}: {{ w.description }}">
{{ w.message or '' }}<br>
<small>Raised {{ as_timestamp(w.raised) | timestamp_custom('${TIME_FORMAT}') if w.raised else 'at an unknown time' }}</small>
</ha-alert>
{% endfor %}
{% endif %}`;
}

function forecastContent(issuedId, areasId) {
  const areas = areasId
    ? `
{% set areas = state_attr('${areasId}', 'areas') or [] %}
{% if areas | count > 0 %}**Areas at risk:** {{ areas | count }}. See NRW for details.{% endif %}`
    : "";
  return `{% set issued = states('${issuedId}') %}
{{ state_attr('${issuedId}', 'summary') or 'No forecast summary is available.' }}

{% set days = state_attr('${issuedId}', 'days') or [] %}
{% if days %}Covers {{ days | first }} to {{ days | last }}.{% endif %}
Issued {{ as_timestamp(issued) | timestamp_custom('${TIME_FORMAT}') if issued not in ['unknown', 'unavailable'] else 'at an unknown time' }}.${areas}`;
}

function gaugeCard(entityId, thresholds) {
  const sorted = [...thresholds].sort((a, b) => a.value - b.value);
  const top = sorted[sorted.length - 1].value;
  const colours = ["var(--warning-color)", "var(--error-color)"];
  return {
    type: "gauge",
    entity: entityId,
    min: 0,
    max: Math.ceil((top * 1.25) / 0.5) * 0.5,
    needle: true,
    segments: [
      { from: 0, color: "var(--success-color)" },
      ...sorted.map((t, i) => ({
        from: t.value,
        color: colours[Math.min(i, colours.length - 1)],
        label: t.label,
      })),
    ],
  };
}

function gaugeSection(hass, deviceId, entities, config) {
  const level = byKey(entities, "level");
  const trend = byKey(entities, "trend");
  const rate = byKey(entities, "rate_of_change");
  const last = byKey(entities, "last_reading");
  const thresholds = (config.thresholds || {})[level];
  const cards = [{ type: "heading", heading: deviceName(hass, deviceId) }];

  if (level && thresholds && thresholds.length) {
    cards.push(gaugeCard(level, thresholds));
    const lines = [...thresholds]
      .sort((a, b) => a.value - b.value)
      .map((t) => `- ${t.value} m: ${t.label}`);
    cards.push({ type: "markdown", content: `**Reference levels**\n${lines.join("\n")}` });
  } else if (level) {
    cards.push({ type: "tile", entity: level });
  }
  for (const id of [trend, rate, last]) {
    if (id) cards.push({ type: "tile", entity: id });
  }
  if (level) {
    cards.push({
      type: "history-graph",
      entities: [{ entity: level }],
      hours_to_show: config.hours_to_show || DEFAULT_HOURS,
    });
  }
  return { type: "grid", cards };
}

function linksContent(hass, gauges, config) {
  const lines = [
    `- [Check flood warnings (NRW)](${NRW_WARNINGS_URL})`,
    `- [River levels, rainfall and sea data (NRW)](${NRW_RIVERS_URL})`,
    "- Floodline: [0345 988 1188](tel:03459881188)",
  ];
  for (const { deviceId, entities } of gauges) {
    const level = byKey(entities, "level");
    const url = hass.states?.[level]?.attributes?.station_url;
    if (url) lines.push(`- [${deviceName(hass, deviceId)} gauge page](${url})`);
  }
  for (const link of config.links || []) {
    lines.push(`- [${link.name}](${link.url})`);
  }
  return lines.join("\n");
}

export async function generateDashboard(config, hass) {
  const title = config.title || DEFAULT_TITLE;
  const entities = nrwEntities(hass, config.entry_id);
  const sections = [];

  if (entities.length === 0) {
    sections.push({
      type: "grid",
      cards: [
        {
          type: "markdown",
          content:
            "No flood data yet. Set up the NRW Flood integration under " +
            "**Settings > Devices & services**, then reload this dashboard.",
        },
      ],
    });
    return { title, views: [{ type: "sections", title, path: VIEW_PATH, sections }] };
  }

  const levelId = byKey(entities, "warning_level");
  if (levelId) {
    sections.push({
      type: "grid",
      cards: [
        { type: "heading", heading: "Flood warnings" },
        { type: "markdown", content: statusContent(levelId) },
      ],
    });
  }

  const devices = new Map();
  for (const e of entities) {
    if (!e.device_id) continue;
    if (!devices.has(e.device_id)) devices.set(e.device_id, []);
    devices.get(e.device_id).push(e);
  }
  const gauges = [...devices.entries()]
    .filter(([, list]) => byKey(list, "level"))
    .map(([deviceId, list]) => ({ deviceId, entities: list }))
    .sort((a, b) => deviceName(hass, a.deviceId).localeCompare(deviceName(hass, b.deviceId)));
  for (const { deviceId, entities: list } of gauges) {
    sections.push(gaugeSection(hass, deviceId, list, config));
  }

  const issuedId = byKey(entities, "forecast_issued");
  if (issuedId) {
    sections.push({
      type: "grid",
      cards: [
        { type: "heading", heading: "5-day flood risk forecast" },
        { type: "markdown", content: forecastContent(issuedId, byKey(entities, "areas_at_risk")) },
      ],
    });
  }

  sections.push({
    type: "grid",
    cards: [
      { type: "heading", heading: "Links" },
      { type: "markdown", content: linksContent(hass, gauges, config) },
    ],
  });

  return {
    title,
    views: [{ type: "sections", title, path: VIEW_PATH, max_columns: 3, sections }],
  };
}

export function registerStrategy(win, registry, BaseClass) {
  const tag = `ll-strategy-dashboard-${STRATEGY_TYPE}`;
  if (!registry.get(tag)) {
    registry.define(
      tag,
      class extends BaseClass {
        static async generate(config, hass) {
          return generateDashboard(config, hass);
        }
      },
    );
  }
  win.customStrategies = win.customStrategies || [];
  if (!win.customStrategies.some((s) => s.type === STRATEGY_TYPE)) {
    win.customStrategies.push({
      type: STRATEGY_TYPE,
      strategyType: "dashboard",
      name: "NRW Flood",
      description: "Flood warnings, river levels and the flood risk forecast from Natural Resources Wales.",
      documentationURL: "https://github.com/proffalken/ha-nrw-flood",
    });
  }
}

if (typeof window !== "undefined" && window.customElements) {
  registerStrategy(window, window.customElements, HTMLElement);
}
