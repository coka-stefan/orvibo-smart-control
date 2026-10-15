/* NVR hard-disk recordings. Calendar values belong to the recorder. */
class OrviboNvrCard extends HTMLElement {
  static getStubConfig() { return {}; }
  setConfig(config) {
    if (config.entity && !String(config.entity).startsWith("camera.")) {
      throw new Error("entity 必须是欧瑞博硬盘回放 camera 实体");
    }
    this._config = config;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (!this._ui) this._build();
    this._sync();
  }
  set hass(value) {
    this._hass = value;
    if (!this._ui) return;
    this._sync();
    if (this._player) this._player.hass = value;
  }
  getCardSize() { return 8; }
  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        ha-card{padding:16px} h2{font-size:20px;margin:0 0 12px}
        label{display:block;margin:12px 0 4px} select,input,button{font:inherit;
          color:var(--primary-text-color);background:var(--card-background-color);border:1px solid var(--divider-color);
          border-radius:6px;padding:9px;box-sizing:border-box;max-width:100%}
        select{width:100%} button{cursor:pointer} button:disabled{opacity:.5;cursor:default}
        .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
        .note,#status{color:var(--secondary-text-color);line-height:1.5;font-size:14px}
        #status{min-height:24px;margin:12px 0} #fragments{max-height:260px;overflow:auto}
        #fragments button{display:block;width:100%;text-align:left;margin:6px 0}
        #player{margin-top:12px}
      </style>
      <ha-card>
        <h2></h2><label for="channel">录像机通道</label><select id="channel"></select>
        <label for="day">录像日期</label><input id="day" type="date">
        <div class="row"><button id="month">查询当月</button><button id="search">查询当天</button>
        <button id="stop">停止回放</button></div>
        <div class="note">日期和时间以录像机显示为准。首次连接可能需要约一分钟。</div>
        <div id="days" class="row"></div><div id="status" role="status" aria-live="polite"></div>
        <div id="fragments"></div>
        <label for="position">指定回放时间</label><div class="row">
        <input id="position" type="datetime-local" step="1"><button id="play">从此时间播放</button></div>
        <div id="player"></div>
      </ha-card>`;
    this._ui = (id) => this.shadowRoot.getElementById(id);
    this._ui("day").value = new Date().toLocaleDateString("sv-SE");
    this._ui("channel").addEventListener("change", () => {
      const previous = this._entity;
      this._entity = this._ui("channel").value;
      this._generation = (this._generation || 0) + 1;
      this._clearPlayer();
      this._ui("fragments").replaceChildren();
      this._ui("days").replaceChildren();
      this._status("");
      if (previous) this._service("stop_hdd_playback", {}, previous).catch(() => {});
    });
    this._ui("day").addEventListener("change", () => {
      this._generation = (this._generation || 0) + 1;
      this._ui("fragments").replaceChildren();
      this._ui("days").replaceChildren();
      this._status("");
    });
    this._ui("month").addEventListener("click", () => this._search("month"));
    this._ui("search").addEventListener("click", () => this._search("day"));
    this._ui("stop").addEventListener("click", () => this._stop());
    this._ui("play").addEventListener("click", () => {
      const value = this._ui("position").value;
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(value)) {
        this._status("请选择有效的录像时间"); return;
      }
      this._play(value.replace(/[-T:]/g, "").padEnd(14, "0"));
    });
  }
  _sync() {
    if (!this._ui || !this._hass) return;
    this.shadowRoot.querySelector("h2").textContent = this._config?.title || "欧瑞博硬盘录像";
    const states = this._hass.states || {};
    const ids = Object.keys(states).filter((id) => id.startsWith("camera.") &&
      states[id].attributes?.video_mode === "hdd_playback" &&
      (!this._config.entity || id === this._config.entity)).sort();
    const select = this._ui("channel");
    const signature = ids.map((id) => `${id}:${states[id].attributes.friendly_name}`).join("|");
    if (signature !== this._options) {
      this._options = signature;
      select.replaceChildren(...ids.map((id) => {
        const option = document.createElement("option");
        option.value = id; option.textContent = states[id].attributes.friendly_name || id; return option;
      }));
      this._entity = ids.includes(this._entity) ? this._entity : ids[0];
      select.value = this._entity || "";
      if (!ids.length) this._status("未找到硬盘回放实体，请更新集成、重启 HA 并选择录像机设备");
    }
    this._busyButtons();
  }
  _busyButtons() {
    if (!this._ui) return;
    for (const id of ["month", "search", "play", "stop"]) {
      this._ui(id).disabled = !!this._busy || !this._entity;
    }
    this._ui("channel").disabled = !!this._busy;
    this._ui("day").disabled = !!this._busy;
    this._ui("position").disabled = !!this._busy;
    for (const element of this._ui("fragments").querySelectorAll("button")) element.disabled = !!this._busy;
    for (const element of this._ui("days").querySelectorAll("button")) element.disabled = !!this._busy;
  }
  _status(text) { this._ui("status").textContent = text; }
  _clearPlayer() { this._player = null; this._ui("player").replaceChildren(); }
  async _service(service, data, entity = this._entity) {
    const result = await this._hass.callWS({ type: "call_service", domain: "orvibo_smart_control",
      service, service_data: { entity_id: entity, ...data }, return_response: true });
    const response = result?.response || result;
    if (!response || response.error) throw new Error("hdd_service_failed");
    return response;
  }
  async _search(operation) {
    if (this._busy || !this._entity) return;
    const date = this._ui("day").value.replace(/-/g, "");
    if (!/^\d{8}$/.test(date)) { this._status("请选择录像日期"); return; }
    const generation = this._generation;
    this._busy = true; this._busyButtons(); this._status("正在连接录像机并查询，请稍候…");
    try {
      const response = await this._service("search_hdd_recordings", { operation,
        date: operation === "month" ? date.slice(0, 6) : date });
      if (generation !== this._generation) return;
      if (response.stage !== "hdd_search_received") {
        this._status(`查询未完成（${this._safeStage(response.stage)}），可稍后重试`); return;
      }
      if (operation === "month") {
        this._ui("days").replaceChildren(...(response.recording_days || []).map((day) => {
          const button = document.createElement("button"); button.textContent = day.slice(6) + " 日";
          button.addEventListener("click", () => {
            this._ui("day").value = `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`;
            this._search("day");
          }); return button;
        }));
        this._status(`当月 ${response.recording_count} 天有录像；点击日期查询片段`);
      } else {
        this._ui("fragments").replaceChildren(...(response.fragments || []).map((row) => {
          const button = document.createElement("button");
          button.textContent = `${this._time(row.start)} — ${this._time(row.end)}　播放`;
          button.addEventListener("click", () => this._play(row.start)); return button;
        }));
        this._status(response.recording_count ? `找到 ${response.recording_count} 个片段${response.fragments_truncated ? "，显示前 256 个，也可指定时间播放" : ""}` : "当天没有录像片段");
      }
    } catch (_) { this._status("查询失败，请稍后重试；可在开发者工具中查看查询操作响应"); }
    finally { this._busy = false; this._busyButtons(); }
  }
  _time(value) { return `${value.slice(8, 10)}:${value.slice(10, 12)}:${value.slice(12, 14)}`; }
  _safeStage(stage) {
    return ["hdd_query_timeout", "hdd_query_failed", "hdd_query_in_progress"].includes(stage) ? stage : "hdd_query_failed";
  }
  async _play(date) {
    if (this._busy || !this._entity) return;
    const generation = this._generation;
    this._busy = true; this._busyButtons(); this._clearPlayer();
    this._status("正在准备回放，播放器连接可能需要约一分钟…");
    try {
      const response = await this._service("start_hdd_playback", { date });
      if (response.stage !== "playback_selected") throw new Error("hdd_start_failed");
      const helpers = await window.loadCardHelpers();
      if (generation !== this._generation) return;
      this._player = helpers.createCardElement({ type: "picture-entity", entity: this._entity,
        camera_view: "live", show_name: false, show_state: false });
      this._player.hass = this._hass;
      this._ui("player").replaceChildren(this._player);
      this._status(`已选择 ${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)} ${this._time(date)}。播放结束或连接失败后，可重新选择片段。`);
    } catch (_) { this._status("回放未能启动，请重新选择片段；也可指定录像机时间重试"); }
    finally { this._busy = false; this._busyButtons(); }
  }
  async _stop() {
    if (this._busy || !this._entity) return;
    this._busy = true; this._busyButtons(); this._clearPlayer();
    try { await this._service("stop_hdd_playback", {}); this._status("已停止回放"); }
    catch (_) { this._status("停止失败，请稍后重试"); }
    finally { this._busy = false; this._busyButtons(); }
  }
}
if (!customElements.get("orvibo-smart-control-nvr-card")) {
  customElements.define("orvibo-smart-control-nvr-card", OrviboNvrCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "orvibo-smart-control-nvr-card")) {
  window.customCards.push({ type: "orvibo-smart-control-nvr-card", name: "欧瑞博硬盘录像",
    description: "按日期查询录像机硬盘片段并回放", preview: false });
}
