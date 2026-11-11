const $ = selector => document.querySelector(selector);
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Session-only preferences remain usable. */ } },
};

export class Enhancements {
  constructor({getState, applyTerminal}) {
    Object.assign(this, {getState, applyTerminal});
    const defaults = {theme:'system', taskFont:14, terminalFont:null};
    const saved = store.get('flightdeck-workspace', {});
    this.prefs = {...defaults};
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      for (const key of Object.keys(defaults)) if (saved[key] !== undefined) this.prefs[key] = saved[key];
    }
    if (!['light', 'dark', 'system'].includes(this.prefs.theme)) this.prefs.theme = defaults.theme;
    for (const [key, min, max] of [['taskFont', 12, 18], ['terminalFont', 10, 22]]) {
      this.prefs[key] = Number.isFinite(this.prefs[key]) ? Math.round(Math.max(min, Math.min(max, this.prefs[key]))) : defaults[key];
    }
    this.mount();
    this.applyPrefs();
    this.events();
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => this.applyPrefs());
  }
  mount() {
    document.body.insertAdjacentHTML('beforeend', `
      <dialog id="settings-dialog" class="settings-dialog" aria-labelledby="settings-title">
        <div class="modal-header"><h2 id="settings-title">Settings</h2><button id="settings-close" class="icon-button" aria-label="Close settings">×</button></div>
        <div class="settings-pages">
          <label class="setting-field">Theme<select id="pref-theme"><option value="system">Match system</option><option value="light">Light</option><option value="dark">Dark</option></select></label>
          <div class="setting-grid"><label class="setting-field">Question text<select id="pref-task-font">${[12,13,14,15,16,17,18].map(n => `<option value="${n}">${n} px</option>`).join('')}</select></label><label class="setting-field">Terminal text<select id="pref-terminal-font">${Array.from({length:13}, (_, i) => i + 10).map(n => `<option value="${n}">${n} px</option>`).join('')}</select></label></div>
        </div>
      </dialog>`);
  }
  applyPrefs() {
    const theme = this.prefs.theme === 'system' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : this.prefs.theme;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.setProperty('--question-font', `${this.prefs.taskFont}px`);
    this.applyTerminal(this.prefs.terminalFont);
    store.set('flightdeck-workspace', this.prefs);
  }
  settings() {
    $('#pref-theme').value = this.prefs.theme;
    $('#pref-task-font').value = this.prefs.taskFont;
    $('#pref-terminal-font').value = this.getState().fontSize;
    $('#settings-dialog').showModal();
  }
  events() {
    document.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
      if (button.id === 'settings-button') this.settings();
      else if (button.id === 'settings-close') $('#settings-dialog').close();
    });
    for (const id of ['pref-theme', 'pref-task-font', 'pref-terminal-font']) {
      $('#' + id).addEventListener('change', () => {
        this.prefs = {...this.prefs, theme:$('#pref-theme').value, taskFont:Number($('#pref-task-font').value), terminalFont:Number($('#pref-terminal-font').value)};
        this.applyPrefs();
      });
    }
  }
}
