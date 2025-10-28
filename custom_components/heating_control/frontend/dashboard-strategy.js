class HeatingControlSmartHeatingStrategy {
  constructor() {
    this.configRequired = false;
    this.noEditor = true;
  }

  async generate(config, hass) {
    const result = await hass.callWS({
      type: "heating_control/generate_dashboard",
      config,
    });

    return result;
  }
}

customElements.define(
  "ll-strategy-dashboard-heating_control-smart-heating",
  HeatingControlSmartHeatingStrategy
);
