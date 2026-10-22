// NRW Flood dashboard strategy.
//
// Served by the integration and loaded on every Home Assistant page. It adds
// an "NRW Flood" option to Settings > Dashboards > Add dashboard. The
// dashboard is rebuilt from the integration's entities each time it opens,
// so new gauges appear without editing anything.
//
// Optional strategy config (edit the dashboard's raw configuration):
//   title: Flood                 # dashboard and view title
//   show_graphs: false           # add a level history graph per gauge
//   hours_to_show: 24            # history graph length
//   entry_id: <config entry id>  # only show one NRW Flood location
//   thresholds:                  # reference levels, drawn as a gauge
//     sensor.wye_at_monmouth_level:
//       - value: 5.2
//         label: Mayhill floods
//   extra_gauges:                # level sensors from other integrations
//     - entity: sensor.old_wye_bridge_stage
//       name: Wye at Hereford      # optional; defaults to the sensor's name
//       trend: sensor.old_wye_bridge_status  # optional trend or status sensor
//       note: Peak reaches Monmouth 14-26 hours later.  # optional
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

NRW's forecast covers the whole of Wales and doesn't name areas. Its maps show the risk area by area, from Very Low to High.

{% set days = state_attr('${issuedId}', 'days') or [] %}
{% if days %}Covers {{ days | first }} to {{ days | last }}.{% endif %}
Issued {{ as_timestamp(issued) | timestamp_custom('${TIME_FORMAT}') if issued not in ['unknown', 'unavailable'] else 'at an unknown time' }}.${areas}`;
}

// A row of small maps, one per forecast day, labelled with the weekday.
function forecastMaps(hass, entities) {
  const cards = [];
  for (let n = 1; n <= 5; n++) {
    const id = byKey(entities, `forecast_map_day_${n}`);
    if (!id) continue;
    const day = hass.states?.[id]?.attributes?.day;
    cards.push({
      type: "picture-entity",
      entity: id,
      name: day ? day.slice(0, 3) : `Day ${n}`,
      show_state: false,
      show_name: true,
    });
  }
  if (!cards.length) return null;
  return { type: "grid", columns: cards.length, square: false, cards, grid_options: { columns: 12 } };
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

const UNAVAILABLE = "['unknown', 'unavailable']";

// Shows a reference level the way it was configured, but always with a decimal
// point, so 6 reads as "6.0 m".
function formatLevel(value) {
  return Number.isInteger(value) ? value.toFixed(1) : String(value);
}

// A Jinja list literal of [value, label, display] for each reference level.
function levelsLiteral(sorted) {
  const items = sorted.map(
    (t) => `[${t.value}, ${JSON.stringify(t.label)}, ${JSON.stringify(formatLevel(t.value))}]`,
  );
  return `[${items.join(", ")}]`;
}

function referenceLines(sorted) {
  return sorted.map((t) => `${formatLevel(t.value)} m: ${t.label}`).join(" · ");
}

// One markdown card per gauge: the level, which way it is going, and how far it
// is from the next reference level.
function riverContent({ level, trend, rate, last }, sorted, note) {
  const lines = [`{% set lvl = states('${level}') %}`];
  lines.push(`{% if lvl in ${UNAVAILABLE} %}
No current reading.
{% else %}
{% set v = lvl | float %}`);
  let reading = "**{{ '%.2f' | format(v) }} m**";
  if (trend) {
    lines.push(`{% set trend = states('${trend}') %}`);
    reading += `, {{ trend if trend not in ${UNAVAILABLE} else 'trend unknown' }}`;
  }
  if (rate) {
    lines.push(`{% set rate = states('${rate}') %}`);
    reading +=
      `{% if rate not in ${UNAVAILABLE} %}` +
      " ({{ '%+.2f' | format(rate | float) }} m/h){% endif %}";
  }
  lines.push(reading);
  if (sorted.length) {
    lines.push(`
{% set levels = ${levelsLiteral(sorted)} %}
{% set ns = namespace(next=none, passed=none) %}
{% for t in levels %}{% if v >= t[0] %}{% set ns.passed = t %}{% elif ns.next is none %}{% set ns.next = t %}{% endif %}{% endfor %}
{% if ns.passed %}<ha-alert alert-type="error">Above {{ ns.passed[1] }} ({{ ns.passed[2] }} m)</ha-alert>{% endif %}
{% if ns.next %}{{ '%.2f' | format(ns.next[0] - v) }} m below {{ ns.next[1] }} ({{ ns.next[2] }} m).{% endif %}`);
  }
  lines.push("{% endif %}");
  if (note) lines.push(`\n${note}`);
  const levels = sorted.length
    ? `Reference levels: ${referenceLines(sorted)}`
    : "No reference levels set.";
  if (last) {
    lines.push(`
{% set last = states('${last}') %}
<small>{% if last not in ${UNAVAILABLE} %}Reading at {{ as_timestamp(last) | timestamp_custom('${TIME_FORMAT}') }}. {% endif %}${levels}</small>`);
  } else {
    lines.push(`\n<small>${levels}</small>`);
  }
  return lines.join("\n");
}

function riverSection(heading, ids, config, note) {
  const sorted = [...((config.thresholds || {})[ids.level] || [])].sort(
    (a, b) => a.value - b.value,
  );
  const cards = [
    { type: "heading", heading },
    { type: "markdown", content: riverContent(ids, sorted, note) },
  ];
  if (sorted.length) cards.push(gaugeCard(ids.level, sorted));
  if (config.show_graphs) {
    cards.push({
      type: "history-graph",
      entities: [{ entity: ids.level }],
      hours_to_show: config.hours_to_show || DEFAULT_HOURS,
    });
  }
  return { type: "grid", cards };
}

function gaugeSection(hass, deviceId, entities, config) {
  return riverSection(
    deviceName(hass, deviceId),
    {
      level: byKey(entities, "level"),
      trend: byKey(entities, "trend"),
      rate: byKey(entities, "rate_of_change"),
      last: byKey(entities, "last_reading"),
    },
    config,
  );
}

// Level sensors from other integrations, such as an Environment Agency gauge
// upstream in England.
function extraGaugeSections(hass, config) {
  return (config.extra_gauges || [])
    .filter((g) => g && g.entity)
    .map((g) =>
      riverSection(
        g.name || hass.states?.[g.entity]?.attributes?.friendly_name || g.entity,
        { level: g.entity, trend: g.trend },
        config,
        g.note,
      ),
    );
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
  sections.push(...extraGaugeSections(hass, config));

  const issuedId = byKey(entities, "forecast_issued");
  if (issuedId) {
    const cards = [
      { type: "heading", heading: "Wales-wide 5-day forecast" },
      { type: "markdown", content: forecastContent(issuedId, byKey(entities, "areas_at_risk")) },
    ];
    const maps = forecastMaps(hass, entities);
    if (maps) cards.push(maps);
    sections.push({ type: "grid", cards });
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

// Home Assistant's frontend installs a scoped custom element registry
// polyfill when it starts, which replaces window.customElements. This script
// is loaded at the same time, so it can define the strategy in the original
// registry just before the swap, where Home Assistant can no longer see it.
// Keep checking for a while after loading and define it again if it has gone.
export function keepStrategyRegistered(
  win,
  { intervalMs = 200, timeoutMs = 60000, timers = globalThis, now = Date.now } = {},
) {
  const attempt = () => {
    try {
      registerStrategy(win, win.customElements, win.HTMLElement);
    } catch (err) {
      // The registry may not be ready yet; the next check tries again.
    }
  };
  attempt();
  const started = now();
  const handle = timers.setInterval(() => {
    if (now() - started > timeoutMs) {
      timers.clearInterval(handle);
      return;
    }
    if (!win.customElements.get(`ll-strategy-dashboard-${STRATEGY_TYPE}`)) attempt();
  }, intervalMs);
}

if (typeof window !== "undefined" && window.customElements) {
  keepStrategyRegistered(window);
}
