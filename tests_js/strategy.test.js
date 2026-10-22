// Tests for the NRW Flood dashboard strategy. Run with: npm test
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  STRATEGY_TYPE,
  generateDashboard,
  registerStrategy,
} from "../custom_components/nrw_flood/frontend/nrw-flood-strategy.js";

const ENTRY = "entry1";

function entity(entity_id, translation_key, device_id, platform = "nrw_flood") {
  return { entity_id, translation_key, device_id, platform, labels: [] };
}

function station(slug, deviceId) {
  return [
    entity(`sensor.${slug}_level`, "level", deviceId),
    entity(`sensor.${slug}_rate_of_change`, "rate_of_change", deviceId),
    entity(`sensor.${slug}_trend`, "trend", deviceId),
    entity(`sensor.${slug}_last_reading`, "last_reading", deviceId),
  ];
}

function makeHass({ withForecast = true, withWarnings = true } = {}) {
  const list = [
    ...station("wye_at_monmouth", "dev_wye"),
    ...station("monnow_at_monnow_gate", "dev_monnow"),
    entity("sensor.other_level", "level", "dev_other", "some_other_integration"),
  ];
  if (withWarnings) {
    list.push(
      entity("sensor.nrw_flood_warnings_warning_level", "warning_level", "dev_warn"),
      entity("sensor.nrw_flood_warnings_active_warnings", "active_warnings", "dev_warn"),
      entity("binary_sensor.nrw_flood_warnings_flood_alert", "flood_alert", "dev_warn"),
      entity("binary_sensor.nrw_flood_warnings_flood_warning", "flood_warning", "dev_warn"),
      entity(
        "binary_sensor.nrw_flood_warnings_severe_flood_warning",
        "severe_flood_warning",
        "dev_warn",
      ),
    );
  }
  if (withForecast) {
    list.push(
      entity("sensor.nrw_flood_risk_forecast_forecast_issued", "forecast_issued", "dev_fc"),
      entity("sensor.nrw_flood_risk_forecast_areas_at_risk", "areas_at_risk", "dev_fc"),
    );
  }
  const device = (name, entry = ENTRY) => ({ name, config_entries: [entry] });
  return {
    entities: Object.fromEntries(list.map((e) => [e.entity_id, e])),
    devices: {
      dev_wye: device("Wye at Monmouth"),
      dev_monnow: { ...device("Monnow at Monnow Gate"), name_by_user: "Monnow (town)" },
      dev_warn: device("NRW flood warnings"),
      dev_fc: device("NRW flood risk forecast"),
      dev_other: device("Something else", "other_entry"),
    },
  };
}

const allCards = (view) => view.sections.flatMap((s) => s.cards);
const findCards = (view, type) => allCards(view).filter((c) => c.type === type);

describe("generateDashboard", () => {
  it("builds one sections view with a stable path for notification links", async () => {
    const dash = await generateDashboard({}, makeHass());
    assert.equal(dash.views.length, 1);
    const [view] = dash.views;
    assert.equal(view.type, "sections");
    assert.equal(view.path, "flood");
    assert.equal(view.title, "Flood");
  });

  it("uses a custom title", async () => {
    const dash = await generateDashboard({ title: "Monmouth floods" }, makeHass());
    assert.equal(dash.title, "Monmouth floods");
    assert.equal(dash.views[0].title, "Monmouth floods");
  });

  it("puts the warnings status first, rendered from the warning level sensor", async () => {
    const [view] = (await generateDashboard({}, makeHass())).views;
    const status = view.sections[0].cards.find((c) => c.type === "markdown");
    assert.ok(status, "status markdown card");
    assert.match(status.content, /sensor\.nrw_flood_warnings_warning_level/);
    assert.match(status.content, /state_attr\(.*'warnings'\)/);
    assert.match(status.content, /ha-alert/);
  });

  it("adds a section per river gauge, sorted by name, using the user's device name", async () => {
    const [view] = (await generateDashboard({}, makeHass())).views;
    const headings = findCards(view, "heading").map((c) => c.heading);
    const monnow = headings.indexOf("Monnow (town)");
    const wye = headings.indexOf("Wye at Monmouth");
    assert.ok(monnow >= 0 && wye >= 0, `headings were ${headings}`);
    assert.ok(monnow < wye);
  });

  it("shows each gauge as one status card built from its level, trend and rate", async () => {
    const [view] = (await generateDashboard({}, makeHass())).views;
    const wye = view.sections.find((s) => s.cards[0].heading === "Wye at Monmouth");
    const status = wye.cards.filter((c) => c.type === "markdown");
    assert.equal(status.length, 1);
    for (const id of [
      "sensor.wye_at_monmouth_level",
      "sensor.wye_at_monmouth_trend",
      "sensor.wye_at_monmouth_rate_of_change",
      "sensor.wye_at_monmouth_last_reading",
    ]) {
      assert.match(status[0].content, new RegExp(id.replace(/\./g, "\\.")), `missing ${id}`);
    }
    assert.equal(findCards(view, "tile").length, 0);
  });

  it("leaves out graphs unless show_graphs is set", async () => {
    const [view] = (await generateDashboard({}, makeHass())).views;
    assert.equal(findCards(view, "history-graph").length, 0);
  });

  it("adds a level graph per gauge when show_graphs is set, honouring hours_to_show", async () => {
    const [view] = (await generateDashboard({ show_graphs: true }, makeHass())).views;
    const graphs = findCards(view, "history-graph");
    assert.equal(graphs.length, 2);
    assert.ok(graphs.every((g) => g.hours_to_show === 24));
    const [longer] = (await generateDashboard({ show_graphs: true, hours_to_show: 72 }, makeHass()))
      .views;
    assert.ok(findCards(longer, "history-graph").every((g) => g.hours_to_show === 72));
  });

  it("ignores entities from other integrations", async () => {
    const [view] = (await generateDashboard({}, makeHass())).views;
    assert.ok(!JSON.stringify(view).includes("sensor.other_level"));
  });

  it("shows a gauge with labelled segments where reference levels are configured", async () => {
    const config = {
      thresholds: {
        "sensor.wye_at_monmouth_level": [
          { value: 6.0, label: "Wye Bridge closed" },
          { value: 5.2, label: "Mayhill floods" },
        ],
      },
    };
    const [view] = (await generateDashboard(config, makeHass())).views;
    const gauges = findCards(view, "gauge");
    assert.equal(gauges.length, 1);
    const [gauge] = gauges;
    assert.equal(gauge.entity, "sensor.wye_at_monmouth_level");
    assert.equal(gauge.min, 0);
    assert.ok(gauge.max > 6.0);
    assert.equal(gauge.needle, true);
    assert.deepEqual(
      gauge.segments.map((s) => [s.from, s.label]),
      [
        [0, undefined],
        [5.2, "Mayhill floods"],
        [6.0, "Wye Bridge closed"],
      ],
    );
  });

  it("works out the distance to the next reference level in the status card", async () => {
    const config = {
      thresholds: {
        "sensor.wye_at_monmouth_level": [
          { value: 6.0, label: "Wye Bridge closed" },
          { value: 5.2, label: "Mayhill floods" },
        ],
      },
    };
    const [view] = (await generateDashboard(config, makeHass())).views;
    const wye = view.sections.find((s) => s.cards[0].heading === "Wye at Monmouth");
    const status = wye.cards.find((c) => c.type === "markdown").content;
    // Levels go into the template sorted, as a Jinja list literal.
    assert.ok(status.includes('[[5.2, "Mayhill floods", "5.2"], [6, "Wye Bridge closed", "6.0"]]'), status);
    assert.match(status, /below/);
    assert.match(status, /above/i);
    // The gauge without reference levels says so rather than guessing.
    const monnow = view.sections.find((s) => s.cards[0].heading === "Monnow (town)");
    assert.match(monnow.cards.find((c) => c.type === "markdown").content, /No reference levels/);
    assert.equal(findCards(view, "gauge").length, 1);
  });

  it("escapes quotes in reference level labels", async () => {
    const config = {
      thresholds: { "sensor.wye_at_monmouth_level": [{ value: 5, label: 'The "Bridge"' }] },
    };
    const [view] = (await generateDashboard(config, makeHass())).views;
    const text = findCards(view, "markdown").map((c) => c.content).join("\n");
    assert.ok(text.includes('[[5, "The \\"Bridge\\"", "5.0"]]'), text);
  });

  it("includes the forecast when the forecast API is configured", async () => {
    const [view] = (await generateDashboard({}, makeHass())).views;
    const text = findCards(view, "markdown").map((c) => c.content).join("\n");
    assert.match(text, /sensor\.nrw_flood_risk_forecast_forecast_issued/);
  });

  it("leaves out warnings and forecast sections when those APIs aren't configured", async () => {
    const hass = makeHass({ withForecast: false, withWarnings: false });
    const [view] = (await generateDashboard({}, hass)).views;
    const text = JSON.stringify(view);
    assert.ok(!text.includes("nrw_flood_warnings"));
    assert.ok(!text.includes("nrw_flood_risk_forecast"));
    assert.ok(text.includes("sensor.wye_at_monmouth_level"));
  });

  it("adds a links section with Floodline and any configured links", async () => {
    const config = { links: [{ name: "Emergency protocols", url: "https://example.test/ep" }] };
    const [view] = (await generateDashboard(config, makeHass())).views;
    const text = findCards(view, "markdown").map((c) => c.content).join("\n");
    assert.match(text, /0345 988 1188/);
    assert.match(text, /\[Emergency protocols\]\(https:\/\/example\.test\/ep\)/);
    assert.match(text, /rivers-and-seas\.naturalresources\.wales/);
  });

  it("can be limited to one config entry", async () => {
    const hass = makeHass();
    hass.devices.dev_monnow.config_entries = ["another_location"];
    const [view] = (await generateDashboard({ entry_id: ENTRY }, hass)).views;
    const headings = findCards(view, "heading").map((c) => c.heading);
    assert.ok(!headings.includes("Monnow (town)"));
    assert.ok(headings.includes("Wye at Monmouth"));
  });

  it("explains what to do when the integration has no entities", async () => {
    const [view] = (await generateDashboard({}, { entities: {}, devices: {} })).views;
    const text = findCards(view, "markdown").map((c) => c.content).join("\n");
    assert.match(text, /NRW Flood integration/);
  });
});

describe("registerStrategy", () => {
  it("defines the custom element and lists it in the new-dashboard dialog", () => {
    const defined = {};
    const win = {};
    const registry = {
      get: (tag) => defined[tag],
      define: (tag, cls) => {
        defined[tag] = cls;
      },
    };

    registerStrategy(win, registry, class {});
    registerStrategy(win, registry, class {}); // loading twice is harmless

    assert.equal(STRATEGY_TYPE, "nrw-flood");
    const cls = defined["ll-strategy-dashboard-nrw-flood"];
    assert.equal(typeof cls.generate, "function");
    assert.equal(win.customStrategies.length, 1);
    assert.deepEqual(
      { type: win.customStrategies[0].type, strategyType: win.customStrategies[0].strategyType },
      { type: "nrw-flood", strategyType: "dashboard" },
    );
    assert.ok(win.customStrategies[0].name);
  });
});
