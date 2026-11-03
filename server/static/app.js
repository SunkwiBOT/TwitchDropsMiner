/* 掉宝矿工面板前端：纯 vanilla JS，无外部依赖。
 * 页签/控件/文案对齐上游 gui.py（主面板 / 掉宝库存 / 设置 / 帮助）。
 * 静态文案由 Jinja 渲染；动态文案从 window.TDM_T 取（服务端按当前语言下发）。
 * 数据全部来自 server/api.py 的 /api/*，写操作后统一 toast 回报。 */
(() => {
  'use strict';

  const RAW = window.TDM_T || {};
  const UI = RAW.ui || {};

  const $ = (id) => document.getElementById(id);
  const CELL_COUNT = 20;
  const TABS = ['main', 'inventory', 'history', 'settings', 'help'];
  const WS_SLOTS = 8;
  const WS_TOPICS_MAX = 50;

  function fmt(template, vars) {
    if (template === undefined || template === null) return '';
    if (!vars) return String(template);
    return String(template).replace(/\{(\w+)\}/g, (match, key) =>
      (vars[key] === undefined ? match : String(vars[key])));
  }

  /* 上游 lang/*.json 的文案：key 形如 gui.inventory.status.active */
  function T(key, vars) {
    return fmt(RAW[key] !== undefined ? RAW[key] : key, vars);
  }

  /* 面板自己的文案（空状态、提示、toast），服务端只给中英两份 */
  function U(key, vars) {
    return fmt(UI[key] !== undefined ? UI[key] : key, vars);
  }

  let currentTab = 'main';
  let logSeq = 0;
  let stateCache = null;
  let settingsCache = null;
  let campaignsCache = null;
  let channelsCache = null;
  let historyCache = null;
  let onlyPriorityHistory = false;
  let countdown = {campaign: null, drop: null};
  let lastNotifAt = 0;

  // 上游把筛选放在 IntVar 里（gui.py:1240-1248），网页上每次刷新页面都算"一次运行"，
  // 所以落到 localStorage，否则改了就像没保存（用户实际报过）。
  const FILTER_KEY = 'tdm.filters.v1';
  const HISTORY_FILTER_KEY = 'tdm.history.onlyPriority';
  const filters = {not_linked: null, upcoming: 1, expired: 0, excluded: 0, finished: 0};

  function loadStoredFilters() {
    try {
      const raw = window.localStorage.getItem(FILTER_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      Object.keys(filters).forEach((key) => {
        if (saved && saved[key] !== undefined && saved[key] !== null) {
          filters[key] = saved[key] ? 1 : 0;
        }
      });
    } catch (e) {
      /* 存储不可用就用上游默认值 */
    }
  }

  function storeFilters() {
    try {
      window.localStorage.setItem(FILTER_KEY, JSON.stringify(filters));
    } catch (e) {
      /* 隐私模式下写不进去，不影响本次显示 */
    }
  }

  loadStoredFilters();

  // ------------------------------------------------------------ 基础件

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function toast(message, kind) {
    const box = $('toasts');
    if (!box) return;
    const node = el('div', 'toast' + (kind === 'ok' ? ' ok' : kind === 'err' ? ' err' : ''), message);
    box.appendChild(node);
    setTimeout(() => node.classList.add('fade'), 3400);
    setTimeout(() => node.remove(), 3900);
  }

  async function api(path, options) {
    const opts = Object.assign({headers: {}}, options || {});
    if (opts.body && typeof opts.body === 'object') {
      opts.body = JSON.stringify(opts.body);
      opts.headers['Content-Type'] = 'application/json';
    }
    const resp = await fetch(path, opts);
    if (resp.status === 401) {
      window.location.href = '/login';
      throw new Error('session expired');
    }
    let data = null;
    try {
      data = await resp.json();
    } catch (e) {
      throw new Error('non-JSON response');
    }
    if (!resp.ok || (data && data.error)) {
      throw new Error((data && data.error) || ('HTTP ' + resp.status));
    }
    return data;
  }

  function confirmModal(title, text) {
    return new Promise((resolve) => {
      const modal = $('modal');
      $('modal-title').textContent = title;
      $('modal-text').textContent = text;
      modal.classList.add('show');
      const done = (value) => {
        modal.classList.remove('show');
        $('modal-yes').removeEventListener('click', yes);
        $('modal-no').removeEventListener('click', no);
        resolve(value);
      };
      const yes = () => done(true);
      const no = () => done(false);
      $('modal-yes').addEventListener('click', yes);
      $('modal-no').addEventListener('click', no);
    });
  }

  /* 进度一律画方格：一格代表一批，精确数字由调用方放进旁边的小字。 */
  function cells(fraction) {
    const wrap = el('div', 'cells');
    const ratio = Math.max(0, Math.min(1, Number(fraction) || 0));
    const filled = Math.round(ratio * CELL_COUNT);
    for (let i = 0; i < CELL_COUNT; i++) {
      wrap.appendChild(el('span', 'cell' + (i < filled ? ' on' : '')));
    }
    return wrap;
  }

  function pill(text, kind) {
    return el('span', 'pill' + (kind ? ' ' + kind : ''), text);
  }

  function fmtTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString(undefined, {hour12: false});
  }

  function fmtDateTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  function fmtSeconds(seconds) {
    const value = Math.max(0, Math.floor(seconds || 0));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = value % 60;
    return String(hours).padStart(2, ' ') + ':' +
      String(minutes).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
  }

  function parseHMS(text) {
    const match = String(text || '').trim().match(/^(\d+):(\d{1,2}):(\d{1,2})$/);
    if (!match) return null;
    return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
  }

  function kvRow(key, value) {
    const r = el('div', 'row');
    r.appendChild(el('span', 'k', key));
    r.appendChild(el('span', 'v',
      value === null || value === undefined || value === '' ? '—' : String(value)));
    return r;
  }

  // --------------------------------------------------------- 主面板

  function renderStatus(state) {
    // 上游把「未关联账户游戏」这个筛选的默认值绑在优先模式上（gui.py:1241）
    if (filters.not_linked === null) {
      filters.not_linked = state.priority_mode === 'PRIORITY_ONLY' ? 1 : 0;
      syncFilterBoxes();
    }
    $('ov-status').textContent = state.status_message || '…';
    $('ov-meta').textContent = U('status_meta', {
      state: state.state || '—',
      campaigns: state.campaign_count || 0,
      channels: state.channel_count || 0,
      claims: state.pending_claims || 0,
    });
    $('tabn-main').textContent = state.pending_claims > 0 ? String(state.pending_claims) : '';
    $('twitch-user').textContent = state.logged_in
      ? `${T('gui.login.logged_in')} ${state.user_id || ''}`.trim()
      : ((state.login || {}).status || T('gui.login.logged_out'));
    $('ov-meta').textContent = U('status_meta', {
      state: state.state || '—',
      campaigns: state.campaign_count || 0,
      channels: state.channel_count || 0,
      claims: state.pending_claims || 0,
    }) + ' · ' + fmtTime(state.server_time);

    const load = state.load || {};
    const card = $('load-card');
    const loading = load.total > 0 && load.done < load.total;
    const justFinished = load.total > 0 && load.finished_at &&
      (state.server_time - load.finished_at) < 10;
    if (loading) {
      card.hidden = false;
      clear($('load-cells')).appendChild(cells(load.done / load.total));
      $('load-cap').textContent = U('load_running', {done: load.done, total: load.total});
    } else if (justFinished) {
      card.hidden = false;
      clear($('load-cells')).appendChild(cells(1));
      $('load-cap').textContent = U('load_done', {total: load.total});
    } else {
      card.hidden = true;
    }

    if (state.progress) {
      const rem = state.progress.remaining || {};
      countdown = {campaign: parseHMS(rem.campaign), drop: parseHMS(rem.drop)};
    }
    renderProgress();
    maybeNotify(state.notifications || []);
  }

  function renderWebsockets(state) {
    const host = clear($('ws-body'));
    const list = state.websockets || {};
    let any = false;
    for (let slot = 0; slot < WS_SLOTS; slot++) {
      const entry = list[slot] || list[String(slot)];
      const r = el('div', 'row');
      r.appendChild(el('span', 'k', T('gui.websocket.websocket', {id: slot})));
      const v = el('span', 'v');
      if (!entry) {
        v.appendChild(el('span', 'muted', '—'));
      } else {
        any = true;
        const status = String(entry.status || T('gui.websocket.initializing'));
        let kind = 'warn';
        if (status.indexOf(T('gui.websocket.connected')) >= 0) kind = 'ok';
        else if (status.indexOf(T('gui.websocket.disconnected')) >= 0) kind = 'err';
        v.appendChild(pill(status, kind));
        v.appendChild(el('span', 'cap',
          ` ${Number(entry.topics || 0)}/${WS_TOPICS_MAX}`));
      }
      r.appendChild(v);
      host.appendChild(r);
    }
    if (!any) host.appendChild(el('p', 'muted', U('ws_empty')));
  }

  let progressKey = null;
  let progressNodes = null;

  /* 主面板的“掉宝活动进度”：游戏封面 + 掉落物品图片。
   * 每秒 tick 只更新文字与方格，只有当前活动/掉宝变了才重建图片节点，
   * 否则每秒重建 <img> 会闪、也会反复请求图片。 */
  function renderProgress() {
    const host = $('progress-body');
    const prog = ((stateCache || {}).progress) || {};
    const drop = prog.drop || {};
    const campaign = prog.campaign || {};
    if (!drop.rewards || drop.rewards === '...') {
      if (progressKey !== '') {
        clear(host);
        host.appendChild(el('p', 'muted', U('progress_empty')));
        progressKey = '';
        progressNodes = null;
      }
      return;
    }

    const claimedSig = (campaign.claimed_items || []).map((item) => item.name || item.drop || '')
      .join('|');
    const key = `${campaign.id || campaign.name || ''}|${drop.id || drop.rewards || ''}|${drop.rewards || ''}|${claimedSig}`;
    if (key !== progressKey || !progressNodes) {
      clear(host);
      progressKey = key;

      const head = el('div', 'prog-head');
      if (campaign.image) {
        const art = el('img', 'prog-art');
        art.src = campaign.image;
        art.alt = '';
        art.loading = 'lazy';
        art.addEventListener('error', () => art.remove());
        head.appendChild(art);
      }
      const info = el('div', 'prog-info');
      info.appendChild(el('div', 'sub',
        T('gui.progress.game') + (campaign.game || '—')));
      info.appendChild(el('div', 'sub',
        T('gui.progress.campaign') + (campaign.name || '—')));
      const campaignLine = el('div', 'lbl');
      info.appendChild(campaignLine);
      const campaignCells = el('div');
      info.appendChild(campaignCells);
      head.appendChild(info);
      host.appendChild(head);

      const benefits = drop.benefits || [];
      host.appendChild(el('div', 'lbl',
        T('gui.progress.drop') + (benefits.length ? '' : (drop.rewards || ''))));
      if (benefits.length) {
        const row = el('div', 'prog-benefits');
        benefits.forEach((benefit) => {
          const box = el('div', 'prog-benefit');
          if (benefit.image) {
            const img = el('img');
            img.src = benefit.image;
            img.alt = '';
            img.loading = 'lazy';
            img.addEventListener('error', () => img.remove());
            box.appendChild(img);
          }
          if (benefit.name) {
            box.appendChild(el('div', 'prog-benefit-name', benefit.name));
          }
          row.appendChild(box);
        });
        host.appendChild(row);
      }

      host.appendChild(el('div', 'sep'));
      const dropLine = el('div', 'lbl');
      host.appendChild(dropLine);
      const dropCells = el('div');
      host.appendChild(dropCells);

      const claimedItems = campaign.claimed_items || [];
      if (claimedItems.length) {
        host.appendChild(el('div', 'sep'));
        host.appendChild(el('div', 'lbl', U('claimed_items')));
        const claimedRow = el('div', 'prog-benefits');
        claimedItems.forEach((item) => {
          const box = el('div', 'prog-benefit claimed');
          if (item.image) {
            const img = el('img');
            img.src = item.image;
            img.alt = '';
            img.loading = 'lazy';
            img.addEventListener('error', () => img.remove());
            box.appendChild(img);
          }
          box.appendChild(el('div', 'prog-benefit-name',
            '✔ ' + (item.name || item.drop || '')));
          claimedRow.appendChild(box);
        });
        host.appendChild(claimedRow);
      }

      progressNodes = {campaignLine, campaignCells, dropLine, dropCells};
    }

    const campaignPct = String(campaign.percentage || '-%').trim();
    const dropPct = String(drop.percentage || '-%').trim();
    progressNodes.campaignLine.textContent =
      T('gui.progress.campaign_progress') + ' ' + campaignPct + '　' +
      T('gui.progress.remaining', {time: countdown.campaign === null
        ? '—' : fmtSeconds(countdown.campaign)});
    clear(progressNodes.campaignCells).appendChild(cells(campaign.progress));
    progressNodes.dropLine.textContent =
      T('gui.progress.drop_progress') + ' ' + dropPct + '　' +
      T('gui.progress.remaining', {time: countdown.drop === null
        ? '—' : fmtSeconds(countdown.drop)});
    clear(progressNodes.dropCells).appendChild(cells(drop.progress));
  }

  function renderChannels() {
    const host = clear($('channels'));
    const channels = channelsCache || [];
    if (!channels.length) {
      $('ch-summary').textContent = U('channels_empty');
      host.appendChild(el('p', 'muted', U('channels_empty_hint')));
      return;
    }
    const online = channels.filter((c) => c.status === 'online').length;
    const watching = channels.filter((c) => c.watching).length;
    $('ch-summary').textContent = U('channels_summary', {
      n: channels.length, online: online, watching: watching,
    });
    const table = el('div', 'table');
    const head = el('div', 'tr head');
    [
      [T('gui.channels.headings.channel'), 'name'],
      [T('gui.channels.headings.status'), ''],
      [T('gui.channels.headings.game'), ''],
      ['🎁', 'center'],
      [T('gui.channels.headings.viewers'), 'num'],
      ['📋', 'center'],
      ['', 'act'],
    ].forEach((pair) => {
      head.appendChild(el('span', 'td ' + pair[1], pair[0]));
    });
    table.appendChild(head);
    const statusText = {
      online: T('gui.channels.online'),
      pending: T('gui.channels.pending'),
      offline: T('gui.channels.offline'),
    };
    channels.forEach((channel) => {
      const tr = el('div', 'tr' + (channel.watching ? ' watching' : ''));
      tr.appendChild(el('span', 'td name', channel.name));
      tr.appendChild(el('span', 'td', statusText[channel.status] || channel.status));
      tr.appendChild(el('span', 'td', channel.game || ''));
      tr.appendChild(el('span', 'td center', channel.drops_enabled ? '✔' : '❌'));
      tr.appendChild(el('span', 'td num', channel.viewers === null ? '' : String(channel.viewers)));
      tr.appendChild(el('span', 'td center', channel.acl_based ? '✔' : '❌'));
      const act = el('span', 'td act');
      const btn = el('button', 'btn quiet small', T('gui.channels.switch'));
      btn.type = 'button';
      btn.disabled = !!channel.watching;
      btn.addEventListener('click', () => switchChannel(channel, btn));
      act.appendChild(btn);
      tr.appendChild(act);
      table.appendChild(tr);
    });
    host.appendChild(table);
  }

  function renderNotifications(state) {
    const host = clear($('ov-notifs'));
    const items = state.notifications || [];
    if (!items.length) {
      host.appendChild(el('p', 'muted', U('notif_empty')));
      return;
    }
    items.forEach((item) => {
      const line = el('div', 'item');
      const grow = el('div', 'grow');
      grow.appendChild(el('div', 'name', item.message || item.title || ''));
      grow.appendChild(el('div', 'sub', fmtTime(item.at)));
      line.appendChild(grow);
      host.appendChild(line);
    });
  }

  /* 托盘通知在网页上的等价物：浏览器通知（需用户授权）。
   * tray_notifications 关掉时上游根本不调用 tray.notify，这里同样不弹。 */
  function maybeNotify(items) {
    const latest = items.reduce((max, item) => Math.max(max, item.at || 0), 0);
    if (!lastNotifAt) {
      lastNotifAt = latest;
      return;
    }
    if (!settingsCache || !settingsCache.tray_notifications) {
      lastNotifAt = latest;
      return;
    }
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') {
      lastNotifAt = latest;
      return;
    }
    items.slice().reverse().forEach((item) => {
      if ((item.at || 0) > lastNotifAt) {
        try {
          new Notification(T('gui.tray.notification_title'), {body: item.message || ''});
        } catch (e) {
          /* 某些 WebView 里构造通知会抛错，忽略 */
        }
      }
    });
    lastNotifAt = latest;
  }

  // ------------------------------------------------------------- 登录

  function renderLogin(state) {
    const host = clear($('login-body'));
    const login = state.login || {};

    host.appendChild(kvRow(U('login_status'),
      state.logged_in ? T('gui.login.logged_in') : (login.status || T('gui.login.logged_out'))));
    host.appendChild(kvRow(U('login_user_id'), state.user_id));

    if (state.logged_in) {
      host.appendChild(el('p', 'hint', U('login_logged_hint')));
      const again = el('button', 'btn', U('login_relogin'));
      again.type = 'button';
      again.addEventListener('click', () => startRelogin(again));
      host.appendChild(again);
      return;
    }

    if (login.kind === 'code') {
      host.appendChild(el('p', null, U('login_code_hint')));
      host.appendChild(el('div', 'code', login.user_code || '------'));
      if (login.verification_uri) {
        const link = el('a', 'link', login.verification_uri);
        link.href = login.verification_uri;
        link.target = '_blank';
        link.rel = 'noopener';
        host.appendChild(link);
      }
      if (login.expires_at && state.server_time) {
        const left = Math.max(0, Math.round(login.expires_at - state.server_time));
        host.appendChild(el('p', 'sub',
          U('login_code_expiry', {minutes: Math.floor(left / 60)})));
      }
      host.appendChild(el('p', 'hint', U('login_poll_hint')));
      const btn = el('button', 'btn', U('login_confirm'));
      btn.type = 'button';
      btn.addEventListener('click', () => {
        refreshState();
        setTimeout(() => {
          refreshState();
          refreshCampaigns();
          refreshChannels();
        }, 1500);
      });
      host.appendChild(btn);
      return;
    }

    if (login.kind === 'password') {
      host.appendChild(el('p', null, U('login_wait_password')));
      const user = el('input');
      user.type = 'text';
      user.placeholder = T('gui.login.username');
      user.autocomplete = 'username';
      const pass = el('input');
      pass.type = 'password';
      pass.placeholder = T('gui.login.password');
      pass.autocomplete = 'current-password';
      const code = el('input');
      code.type = 'text';
      code.placeholder = T('gui.login.twofa_code');
      [user, pass, code].forEach((node) => host.appendChild(node));
      const btn = el('button', 'btn primary', T('gui.login.button'));
      btn.type = 'button';
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          await api('/api/twitch/password', {
            method: 'POST',
            body: {username: user.value.trim(), password: pass.value, token: code.value.trim()},
          });
          toast(U('toast_submitted'), 'ok');
          setTimeout(refreshState, 1500);
        } catch (e) {
          toast(e.message, 'err');
          btn.disabled = false;
        }
      });
      host.appendChild(btn);
      return;
    }

    host.appendChild(el('p', 'hint', T('gui.login.request')));
    const start = el('button', 'btn primary', U('login_start'));
    start.type = 'button';
    start.addEventListener('click', () => startRelogin(start));
    host.appendChild(start);
  }

  async function startRelogin(btn) {
    if (stateCache && stateCache.logged_in) {
      if (!await confirmModal(U('relogin_title'), U('relogin_text'))) return;
    }
    btn.disabled = true;
    try {
      await api('/api/twitch/relogin', {method: 'POST', body: {}});
      toast(U('toast_relogin'), 'ok');
      setTimeout(() => {
        refreshState();
        btn.disabled = false;
      }, 1500);
    } catch (e) {
      toast(e.message, 'err');
      btn.disabled = false;
    }
  }

  // --------------------------------------------------------- 掉宝库存

  function dropStateText(drop) {
    /* 逐条对齐 gui.InventoryOverview.update_progress（gui.py:1507-1544） */
    if (drop.is_claimed) return {text: T('gui.inventory.status.claimed'), kind: 'ok'};
    if (drop.can_claim) return {text: T('gui.inventory.status.ready_to_claim'), kind: 'warn'};
    if (drop.current || drop.can_earn) {
      let text = T('gui.inventory.percent_progress', {
        minutes: drop.required, percent: String(drop.percentage || '').trim(),
      });
      if (drop.show_ends) {
        text += '\n' + T('gui.inventory.ends', {time: drop.ends});
      }
      return {text: text, kind: ''};
    }
    let text = drop.required > 0
      ? T('gui.inventory.minutes_progress', {minutes: drop.required}) : '';
    if (drop.show_starts) {
      text += '\n' + T('gui.inventory.starts', {time: drop.starts});
    } else if (drop.show_ends) {
      text += '\n' + T('gui.inventory.ends', {time: drop.ends});
    }
    return {text: text || '—', kind: ''};
  }

  function campaignVisible(campaign) {
    /* 对齐 gui.py:1327-1353 的 _update_visibility */
    if (campaign.required_minutes <= 0) return false;  // 纯订阅类活动上游不显示
    if (!(filters.not_linked === 1 || campaign.eligible)) return false;
    if (!(campaign.active
      || (filters.upcoming === 1 && campaign.upcoming)
      || (filters.expired === 1 && campaign.expired))) return false;
    if (!(filters.excluded === 1
      || (!campaign.excluded && (!campaign.priority_only || campaign.in_priority)))) return false;
    if (!(filters.finished === 1 || !campaign.finished)) return false;
    return true;
  }

  function renderCampaigns() {
    const host = clear($('campaigns'));
    const all = campaignsCache || [];
    if (!all.length) {
      $('inv-summary').textContent = '';
      const empty = el('div', 'empty');
      empty.appendChild(el('b', null, U('inv_empty_title')));
      empty.appendChild(el('span', null, U('inv_empty_text')));
      host.appendChild(empty);
      return;
    }
    const visible = all.filter(campaignVisible);
    $('inv-summary').textContent = U('inv_summary', {n: all.length, m: visible.length});
    if (!visible.length) {
      host.appendChild(el('p', 'muted', U('inv_no_match')));
      return;
    }
    visible.forEach((campaign) => {
      const card = el('div', 'card campaign');
      if (campaign.image_url) {
        const art = el('img', 'boxart');
        art.src = campaign.image_url;
        art.alt = '';
        art.loading = 'lazy';
        art.addEventListener('error', () => art.remove());
        card.appendChild(art);
      }
      const info = el('div', 'c-info');
      info.appendChild(el('div', 'c-name', campaign.name));
      const statusLine = el('div', 'c-line');
      statusLine.appendChild(pill(
        campaign.active ? T('gui.inventory.status.active')
          : (campaign.upcoming ? T('gui.inventory.status.upcoming')
            : T('gui.inventory.status.expired')),
        campaign.active ? 'ok' : (campaign.upcoming ? 'warn' : 'err')));
      statusLine.appendChild(el('span', 'cap', '　' + (campaign.game || '—')));
      info.appendChild(statusLine);
      info.appendChild(el('div', 'sub', T('gui.inventory.ends', {time: campaign.ends || '—'})));
      info.appendChild(el('div', 'sub', T('gui.inventory.starts', {time: campaign.starts || '—'})));
      // 关联状态：上游是可点击的 LinkLabel，指向 campaign.link_url
      const linked = campaign.linked
        || (campaign.has_badge_or_emote && settingsCache && settingsCache.enable_badges_emotes);
      const linkLine = el('div', 'sub');
      const link = el('a', 'link inline',
        linked ? T('gui.inventory.status.linked') : T('gui.inventory.status.not_linked'));
      link.href = campaign.link_url || 'https://www.twitch.tv/drops/campaigns';
      link.target = '_blank';
      link.rel = 'noopener';
      linkLine.appendChild(link);
      info.appendChild(linkLine);
      const acl = campaign.allowed_channels || [];
      info.appendChild(el('div', 'sub strong', T('gui.inventory.allowed_channels')));
      if (!acl.length) {
        info.appendChild(el('div', 'sub', T('gui.inventory.all_channels')));
      } else {
        acl.slice(0, campaign.allowed_more ? 4 : 5).forEach((name) => {
          info.appendChild(el('div', 'sub', name));
        });
        if (campaign.allowed_more) {
          info.appendChild(el('div', 'sub',
            T('gui.inventory.and_more', {amount: campaign.allowed_more})));
        }
      }
      card.appendChild(info);

      const drops = el('div', 'drops');
      (campaign.drops || []).forEach((drop) => {
        const box = el('div', 'dropbox');
        const benefits = drop.benefits || [];
        if (benefits.length) {
          benefits.forEach((benefit) => {
            const b = el('div', 'benefit', benefit.name || '');
            if (benefit.image_url) {
              const img = el('img', 'benefit-img');
              img.src = benefit.image_url;
              img.alt = '';
              img.loading = 'lazy';
              img.addEventListener('error', () => img.remove());
              b.insertBefore(img, b.firstChild);
            }
            box.appendChild(b);
          });
        } else if (drop.rewards) {
          box.appendChild(el('div', 'benefit', drop.rewards));
        }
        const st = dropStateText(drop);
        box.appendChild(el('div', 'd-status' + (st.kind ? ' ' + st.kind : ''), st.text));
        box.appendChild(cells(drop.progress));
        if (drop.can_claim) {
          const btn = el('button', 'btn go small', U('claim'));
          btn.type = 'button';
          btn.addEventListener('click', () => claimDrop(drop, btn));
          box.appendChild(btn);
        }
        drops.appendChild(box);
      });
      card.appendChild(drops);
      host.appendChild(card);
    });
  }

  // --------------------------------------------------------- 历史掉宝

  function loadHistoryFilter() {
    try {
      onlyPriorityHistory = window.localStorage.getItem(HISTORY_FILTER_KEY) === '1';
    } catch (e) {
      onlyPriorityHistory = false;
    }
    const box = $('hist-only-priority');
    if (box) box.checked = onlyPriorityHistory;
  }

  function storeHistoryFilter() {
    try {
      window.localStorage.setItem(HISTORY_FILTER_KEY, onlyPriorityHistory ? '1' : '0');
    } catch (e) {
      /* 隐私模式忽略 */
    }
  }

  function renderHistory(data) {
    historyCache = data || {games: [], total: 0, priority: []};
    const groups = (historyCache.games || []).filter(
      (group) => !onlyPriorityHistory || group.in_priority);
    let count = 0;
    let withRecords = 0;
    groups.forEach((group) => {
      count += (group.items || []).length;
      if ((group.items || []).length) withRecords += 1;
    });
    $('hist-summary').textContent = U('history_summary', {n: count, m: withRecords});
    $('tabn-history').textContent = historyCache.total ? String(historyCache.total) : '';
    const host = clear($('history-groups'));
    if (!groups.length) {
      host.appendChild(el('div', 'empty',
        onlyPriorityHistory ? U('history_empty_priority') : U('history_empty')));
      return;
    }
    groups.forEach((group) => {
      const card = el('div', 'card history-game');
      const head = el('div', 'hist-head');
      if (group.image) {
        const art = el('img', 'hist-art');
        art.src = group.image;
        art.alt = '';
        art.loading = 'lazy';
        art.addEventListener('error', () => art.remove());
        head.appendChild(art);
      }
      const grow = el('div', 'grow');
      grow.appendChild(el('div', 'name', group.game || U('history_unknown_game')));
      if ((group.items || []).length) {
        grow.appendChild(el('div', 'cap', U('history_group_meta', {
          n: group.count || group.items.length,
          time: fmtDateTime(group.latest),
        })));
      } else {
        grow.appendChild(el('div', 'cap', U('history_group_empty')));
      }
      head.appendChild(grow);
      if (group.in_priority) {
        head.appendChild(pill(U('history_priority', {n: group.priority_index + 1}), 'ok'));
      }
      card.appendChild(head);
      const grid = el('div', 'hist-grid');
      (group.items || []).forEach((item) => {
        const box = el('div', 'hist-item');
        const image = item.image || group.image;
        if (image) {
          const img = el('img');
          img.src = image;
          img.alt = '';
          img.loading = 'lazy';
          img.addEventListener('error', () => img.remove());
          box.appendChild(img);
        }
        const itemName = item.name || item.drop_name || '—';
        const itemCount = Number(item.count || 1);
        box.appendChild(el('div', 'hname',
          itemCount > 1 ? `${itemName} ×${itemCount}` : itemName));
        if (item.campaign_name) {
          box.appendChild(el('div', 'hmeta',
            U('history_campaign_meta', {campaign: item.campaign_name})));
        }
        const stamp = item.claimed_at || item.first_seen;
        box.appendChild(el('div', 'hmeta', item.claimed_at
          ? U('history_claimed_at', {time: fmtDateTime(stamp)})
          : U('history_recorded_at', {time: fmtDateTime(stamp)})));
        grid.appendChild(box);
      });
      card.appendChild(grid);
      host.appendChild(card);
    });
  }

  async function refreshHistory() {
    try {
      renderHistory(await api('/api/history'));
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  // ------------------------------------------------------------- 设置

  function renderSettings(data) {
    settingsCache = data;
    $('set-mode').value = data.priority_mode || 'ENDING_SOONEST';
    $('set-quality').value = String(data.connection_quality || 1);
    $('set-proxy').value = data.proxy || '';
    $('set-tray-notif').checked = !!data.tray_notifications;
    $('set-dark-mode').checked = !!data.dark_mode;
    $('set-unlinked').checked = !!data.unlinked_campaigns;
    $('set-badges').checked = !!data.enable_badges_emotes;
    $('set-availcheck').checked = !!data.available_drops_check;
    $('set-autostart-tray').checked = !!data.autostart_tray;

    const auto = $('set-autostart');
    auto.checked = !!data.autostart;
    auto.disabled = !data.autostart_available;
    $('autostart-hint').hidden = !!data.autostart_available;

    const lang = $('set-language');
    const list = (stateCache && stateCache.languages && stateCache.languages.length)
      ? stateCache.languages : [data.language || 'English'];
    if (lang.options.length !== list.length) {
      while (lang.firstChild) lang.removeChild(lang.firstChild);
      list.forEach((name) => lang.appendChild(new Option(name, name)));
    }
    if (data.language) lang.value = data.language;

    if (filters.not_linked === null) {
      filters.not_linked = data.priority_mode === 'PRIORITY_ONLY' ? 1 : 0;
      syncFilterBoxes();
    }

    renderList($('prio-list'), data.priority || [], 'priority');
    renderList($('excl-list'), data.exclude || [], 'exclude');
    ['priority', 'exclude'].forEach(renderPicker);
  }

  // ------------------------------------------------------ 游戏候选选择器
  // 不用原生 datalist：安卓 Chrome/WebView 根本不弹那个下拉，点了没反应。
  // 候选来源与上游一致 = gui.set_games(库存里的游戏) + 已加进列表的名字。

  const PICKER = {
    priority: {input: 'prio-input', toggle: 'prio-toggle', box: 'prio-suggest', count: 'prio-count', open: false},
    exclude: {input: 'excl-input', toggle: 'excl-toggle', box: 'excl-suggest', count: 'excl-count', open: false},
  };
  const SUGGEST_LIMIT = 200;

  function candidatePool() {
    const set = new Set();
    ((settingsCache && settingsCache.available_games) || []).forEach((n) => n && set.add(n));
    return [...set].sort((a, b) => a.localeCompare(b, 'en'));
  }

  function renderPicker(kind) {
    const cfg = PICKER[kind];
    const current = kind === 'priority'
      ? (settingsCache && settingsCache.priority) || []
      : (settingsCache && settingsCache.exclude) || [];
    const added = new Set(current);
    const pool = candidatePool().filter((n) => !added.has(n));
    $(cfg.count).textContent = String(pool.length);
    const box = $(cfg.box);
    $(cfg.toggle).setAttribute('aria-expanded', cfg.open ? 'true' : 'false');
    box.hidden = !cfg.open;
    if (!cfg.open) return;
    clear(box);
    const query = ($(cfg.input).value || '').trim().toLowerCase();
    const matches = query ? pool.filter((n) => n.toLowerCase().includes(query)) : pool;
    if (!matches.length) {
      box.appendChild(el('p', 'muted', query
        ? U('cand_none', {q: query}) : U('cand_hint')));
      return;
    }
    matches.slice(0, SUGGEST_LIMIT).forEach((name) => {
      const chip = el('button', 'chip', name);
      chip.type = 'button';
      chip.addEventListener('click', () => addNamed(kind, name));
      box.appendChild(chip);
    });
    if (matches.length > SUGGEST_LIMIT) {
      box.appendChild(el('p', 'cap', `${matches.length} …`));
    }
  }

  function togglePicker(kind) {
    PICKER[kind].open = !PICKER[kind].open;
    renderPicker(kind);
  }

  function renderList(host, items, kind) {
    clear(host);
    if (!items.length) {
      host.appendChild(el('p', 'muted', kind === 'priority' ? U('prio_empty') : U('excl_empty')));
      return;
    }
    items.forEach((name, index) => {
      const li = el('li', 'item');
      const grow = el('div', 'grow');
      grow.appendChild(el('div', 'name', name));
      li.appendChild(grow);
      if (kind === 'priority') {
        li.appendChild(listButton('⇈', index > 0, () => movePriority(index, 'top')));
        li.appendChild(listButton('↑', index > 0, () => movePriority(index, 1)));
        li.appendChild(listButton('↓', index < items.length - 1, () => movePriority(index, -1)));
        li.appendChild(listButton('⇊', index < items.length - 1, () => movePriority(index, 'bottom')));
      }
      li.appendChild(listButton('❌', true, () => removeItem(kind, name)));
      host.appendChild(li);
    });
  }

  function listButton(label, enabled, onClick) {
    const btn = el('button', 'btn quiet small', label);
    btn.type = 'button';
    btn.disabled = !enabled;
    btn.addEventListener('click', onClick);
    return btn;
  }

  async function removeItem(kind, name) {
    try {
      await api(kind === 'priority' ? '/api/priority' : '/api/exclude',
        {method: 'POST', body: {action: 'remove', game: name}});
      toast(U('toast_removed', {name: name}), 'ok');
      await refreshSettings();
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  async function movePriority(index, direction) {
    try {
      const body = (direction === 'top' || direction === 'bottom')
        ? {action: direction, index: index}
        : {action: 'move', index: index, direction: direction};
      await api('/api/priority', {method: 'POST', body: body});
      await refreshSettings();
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  async function addItem(kind) {
    const input = $(kind === 'priority' ? 'prio-input' : 'excl-input');
    const name = (input.value || '').trim();
    if (!name) return;
    await addNamed(kind, name);
  }

  async function addNamed(kind, name) {
    const input = $(kind === 'priority' ? 'prio-input' : 'excl-input');
    try {
      await api(kind === 'priority' ? '/api/priority' : '/api/exclude',
        {method: 'POST', body: {action: 'add', game: name}});
      input.value = '';
      toast(U('toast_added', {name: name}), 'ok');
      await refreshSettings();
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  async function patchSettings(body, opts) {
    const options = opts || {};
    try {
      const data = await api('/api/settings', {method: 'POST', body: body});
      if (options.toast) toast(U('toast_saved'), 'ok');
      if (options.refresh !== false) await refreshSettings();
      return data;
    } catch (e) {
      toast(e.message, 'err');
      if (options.onError) options.onError();
      throw e;
    }
  }

  // ------------------------------------------------------------- 筛选

  const FILTER_BOXES = {
    not_linked: 'f-not_linked',
    upcoming: 'f-upcoming',
    expired: 'f-expired',
    excluded: 'f-excluded',
    finished: 'f-finished',
  };

  function syncFilterBoxes() {
    Object.keys(FILTER_BOXES).forEach((key) => {
      $(FILTER_BOXES[key]).checked = filters[key] === 1;
    });
  }

  function readFilterBoxes() {
    Object.keys(FILTER_BOXES).forEach((key) => {
      filters[key] = $(FILTER_BOXES[key]).checked ? 1 : 0;
    });
    storeFilters();
  }

  // ------------------------------------------------------------- 操作

  async function switchChannel(channel, btn) {
    btn.disabled = true;
    try {
      await api('/api/channel/switch', {method: 'POST', body: {iid: channel.iid}});
      toast(U('toast_switch', {name: channel.name}), 'ok');
      setTimeout(() => { refreshChannels(); refreshState(); }, 1500);
    } catch (e) {
      toast(e.message, 'err');
      btn.disabled = false;
    }
  }

  async function claimDrop(drop, btn) {
    btn.disabled = true;
    try {
      await api('/api/drop/claim', {method: 'POST', body: {drop_id: drop.id}});
      toast(U('toast_claimed', {name: drop.rewards || drop.name || drop.id}), 'ok');
      await refreshCampaigns();
    } catch (e) {
      toast(e.message, 'err');
      btn.disabled = false;
    }
  }

  async function logoutTwitch() {
    if (!await confirmModal(U('logout_title'), U('logout_text'))) return;
    try {
      const data = await api('/api/twitch/logout', {method: 'POST', body: {}});
      toast(data.revoked ? U('logout_ok') : U('logout_local'), 'ok');
      burstRefresh();
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  async function reloadInventory() {
    try {
      await api('/api/reload', {method: 'POST', body: {}});
      toast(U('toast_reload'), 'ok');
      burstRefresh();
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  // ------------------------------------------------------------- 拉取

  async function refreshState() {
    try {
      const state = await api('/api/state');
      stateCache = state;
      $('conn-dot').className = 'dot ok';
      $('conn-text').textContent = U('conn_connected');
      renderStatus(state);
      renderLogin(state);
      renderWebsockets(state);
      renderNotifications(state);
      if (state.version && $('about-version').textContent === '—') {
        $('about-version').textContent = 'v' + state.version;
      }
    } catch (e) {
      $('conn-dot').className = 'dot err';
      $('conn-text').textContent = U('conn_lost');
    }
  }

  async function refreshCampaigns() {
    try {
      const data = await api('/api/campaigns');
      campaignsCache = data.campaigns || [];
      renderCampaigns();
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  async function refreshChannels() {
    try {
      const data = await api('/api/channels');
      channelsCache = data.channels || [];
    } catch (e) {
      channelsCache = [];
    }
    renderChannels();
  }

  async function refreshSettings() {
    try {
      renderSettings(await api('/api/settings'));
    } catch (e) {
      toast(e.message, 'err');
    }
  }

  function appendLogLines(lines) {
    const body = $('log-body');
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    lines.forEach((line) => {
      const row = el('div', 'log-line');
      row.appendChild(el('span', 't', fmtTime(line.at)));
      row.appendChild(el('span', null, line.text));
      body.appendChild(row);
    });
    while (body.childElementCount > 400) body.removeChild(body.firstChild);
    if (atBottom) body.scrollTop = body.scrollHeight;
    $('log-count').textContent = String(body.childElementCount);
  }

  let logsBusy = false;
  async function refreshLogs() {
    if (logsBusy) return;
    logsBusy = true;
    try {
      const data = await api(`/api/logs?since=${logSeq}`);
      logSeq = data.seq;
      if (data.lines && data.lines.length) appendLogLines(data.lines);
    } catch (e) {
      /* 日志拉取失败不打扰用户 */
    } finally {
      logsBusy = false;
    }
  }

  /* 触发刷新后短时间高频轮询：库存载入常常两三秒就完事，3 秒一轮会整个错过。 */
  let burstTimer = null;
  function burstRefresh() {
    let left = 20;
    if (burstTimer) clearInterval(burstTimer);
    burstTimer = setInterval(() => {
      refreshState();
      if (currentTab === 'inventory') refreshCampaigns();
      if (currentTab === 'main') refreshChannels();
      if (--left <= 0) {
        clearInterval(burstTimer);
        burstTimer = null;
      }
    }, 700);
  }

  // ------------------------------------------------------------- 页签

  function showTab(name) {
    currentTab = name;
    TABS.forEach((tab) => {
      const on = tab === name;
      $('tab-' + tab).hidden = !on;
      $('tabbtn-' + tab).setAttribute('aria-selected', on ? 'true' : 'false');
    });
    window.scrollTo(0, 0);
    try {
      if (window.location.hash !== '#' + name) {
        window.history.replaceState(null, '', '#' + name);
      }
    } catch (e) {
      /* file:// 或老 WebView 忽略 */
    }
    if (name === 'inventory') refreshCampaigns();
    if (name === 'history') refreshHistory();
    if (name === 'settings') refreshSettings();
    if (name === 'main') refreshChannels();
  }

  /* 「剩余 H:MM:SS」每秒本地推进一次，和上游的倒计时控件一致。 */
  function startProgressTicker() {
    setInterval(() => {
      if (currentTab !== 'main' || !stateCache) return;
      if (countdown.campaign !== null && countdown.campaign > 0) countdown.campaign -= 1;
      if (countdown.drop !== null && countdown.drop > 0) countdown.drop -= 1;
      renderProgress();
    }, 1000);
  }

  // ------------------------------------------------------------- 启动

  function start() {
    TABS.forEach((tab) => {
      $(`tabbtn-${tab}`).addEventListener('click', () => showTab(tab));
    });

    $('prio-add').addEventListener('click', () => addItem('priority'));
    $('excl-add').addEventListener('click', () => addItem('exclude'));
    $('prio-toggle').addEventListener('click', () => togglePicker('priority'));
    $('excl-toggle').addEventListener('click', () => togglePicker('exclude'));
    ['prio-input', 'excl-input'].forEach((id) => {
      const kind = id === 'prio-input' ? 'priority' : 'exclude';
      $(id).addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') {
          ev.preventDefault();
          addItem(kind);
        }
      });
      $(id).addEventListener('input', () => {
        PICKER[kind].open = true;
        renderPicker(kind);
      });
      $(id).addEventListener('focus', () => {
        PICKER[kind].open = true;
        renderPicker(kind);
      });
    });

    // 设置项：逐项立即保存（与上游“勾选即生效”一致）
    $('set-language').addEventListener('change', async (ev) => {
      const value = ev.target.value;
      try {
        await api('/api/settings', {method: 'POST', body: {language: value}});
        window.location.reload();
      } catch (e) {
        toast(e.message, 'err');
        refreshSettings();
      }
    });
    $('set-autostart').addEventListener('change', async (ev) => {
      const checked = ev.target.checked;
      try {
        await api('/api/settings', {method: 'POST', body: {autostart: checked}});
        toast(checked ? U('autostart_on') : U('autostart_off'), 'ok');
      } catch (e) {
        toast(e.message, 'err');
        ev.target.checked = !checked;
      }
    });
    $('set-tray-notif').addEventListener('change', (ev) => {
      const checked = ev.target.checked;
      if (checked && typeof Notification !== 'undefined' && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
      }
      patchSettings({tray_notifications: checked});
    });
    $('set-dark-mode').addEventListener('change', (ev) => {
      document.body.classList.toggle('light', !ev.target.checked);
      patchSettings({dark_mode: ev.target.checked}, {refresh: false});
    });
    $('set-unlinked').addEventListener('change', (ev) => {
      patchSettings({unlinked_campaigns: ev.target.checked});
    });
    $('set-badges').addEventListener('change', (ev) => {
      patchSettings({enable_badges_emotes: ev.target.checked});
    });
    $('set-availcheck').addEventListener('change', (ev) => {
      patchSettings({available_drops_check: ev.target.checked});
    });
    $('set-mode').addEventListener('change', (ev) => {
      patchSettings({priority_mode: ev.target.value});
    });
    $('set-quality').addEventListener('change', (ev) => {
      patchSettings({connection_quality: Number(ev.target.value)});
    });
    const proxy = $('set-proxy');
    const saveProxy = () => {
      const value = proxy.value.trim();
      if (settingsCache && value === (settingsCache.proxy || '')) return;
      patchSettings({proxy: value}, {toast: true}).catch(() => {});
    };
    proxy.addEventListener('change', saveProxy);
    proxy.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        saveProxy();
        proxy.blur();
      }
    });

    $('set-reload').addEventListener('click', reloadInventory);
    $('inv-refresh').addEventListener('click', () => {
      readFilterBoxes();
      renderCampaigns();
      reloadInventory();
    });
    Object.keys(FILTER_BOXES).forEach((key) => {
      $(FILTER_BOXES[key]).addEventListener('change', () => {
        readFilterBoxes();
        renderCampaigns();
        toast(U('toast_filter_saved'), 'ok');
      });
    });
    $('twitch-logout').addEventListener('click', logoutTwitch);

    loadHistoryFilter();
    $('hist-only-priority').addEventListener('change', (ev) => {
      onlyPriorityHistory = ev.target.checked;
      storeHistoryFilter();
      if (historyCache) renderHistory(historyCache);
    });
    $('hist-refresh').addEventListener('click', refreshHistory);

    syncFilterBoxes();
    const initialTab = (window.location.hash || '').replace(/^#/, '');
    showTab(TABS.includes(initialTab) ? initialTab : 'main');
    window.addEventListener('hashchange', () => {
      const tab = (window.location.hash || '').replace(/^#/, '');
      if (TABS.includes(tab) && tab !== currentTab) showTab(tab);
    });
    startProgressTicker();
    refreshState();
    refreshSettings();
    refreshChannels();
    refreshLogs();
    setInterval(refreshState, 3000);
    setInterval(refreshLogs, 1500);
    setInterval(() => {
      if (currentTab === 'inventory') refreshCampaigns();
      if (currentTab === 'main') refreshChannels();
      if (currentTab === 'settings' && !settingsCache) refreshSettings();
    }, 8000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
