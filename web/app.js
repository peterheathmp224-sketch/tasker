/* Tasker Mini App — vanilla JS, no build. API: same FastAPI /api/* */
(function () {
  "use strict";
  const app = document.getElementById("app");
  const tg = window.Telegram && window.Telegram.WebApp;
  try { tg && tg.ready(); tg && tg.expand(); } catch (e) {}

  const initData = () => { try { return (tg && tg.initData) || ""; } catch (e) { return ""; } };
  const tgUser = () => { try { return (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) || null; } catch (e) { return null; } };
  const STATUS_RU = { new: "Новая", in_progress: "В работе", done: "Готово" };
  const today = () => new Date().toISOString().slice(0, 10);

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function req(path, opts) {
    opts = opts || {};
    const r = await fetch(path, {
      method: opts.method || "GET",
      headers: Object.assign({ "Content-Type": "application/json", "X-Telegram-Init-Data": initData() }, opts.headers || {}),
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  const api = {
    me: () => req("/api/users/me"),
    users: (s) => req("/api/users" + (s ? "?search=" + encodeURIComponent(s) : "")),
    tasks: (q) => req("/api/tasks" + (q || "")),
    task: (id) => req("/api/tasks/" + id),
    createTask: (b) => req("/api/tasks", { method: "POST", body: b }),
    patchTask: (id, b) => req("/api/tasks/" + id, { method: "PATCH", body: b }),
    deleteTask: (id) => req("/api/tasks/" + id, { method: "DELETE" }),
    groups: () => req("/api/groups"),
    createGroup: (name) => req("/api/groups", { method: "POST", body: { name } }),
    deleteGroup: (id) => req("/api/groups/" + id, { method: "DELETE" }),
    addMember: (id, b) => req("/api/groups/" + id + "/members", { method: "POST", body: b }),
    removeMember: (g, u) => req("/api/groups/" + g + "/members/" + u, { method: "DELETE" }),
    calendar: (q) => req("/api/calendar" + (q || "")),
    attachments: (taskId) => req("/api/tasks/" + taskId + "/attachments"),
    deleteAttachment: (taskId, attId) => req("/api/tasks/" + taskId + "/attachments/" + attId, { method: "DELETE" }),
  };
  const attachmentUrl = (taskId, attId) => "/api/tasks/" + taskId + "/attachments/" + attId;

  async function uploadAttachment(taskId, file) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    const r = await fetch("/api/tasks/" + taskId + "/attachments", {
      method: "POST",
      headers: { "X-Telegram-Init-Data": initData() },
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  function fmtSize(n) {
    n = Number(n || 0);
    if (n < 1024) return n + " Б";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " КБ";
    return (n / 1024 / 1024).toFixed(1) + " МБ";
  }

  function attachmentsBlock(t) {
    const list = t.attachments || [];
    return '<h3>Файлы (' + list.length + ")</h3>" +
      (list.map((a) =>
        '<div class="row file-row"><a style="flex:1" href="' + esc(a.url || attachmentUrl(t.id, a.id)) + '" data-dl-file="' + a.id + '" data-fname="' + esc(a.filename) + '">📎 ' +
        esc(a.filename) + ' <span class="muted">(' + esc(fmtSize(a.size)) + ")</span></a>" +
        '<button class="ghost" data-del-file="' + a.id + '">✕</button></div>'
      ).join("") || '<p class="muted">Файлов пока нет</p>') +
      '<div class="row" style="margin-top:6px"><input id="f-file" type="file" multiple><button id="f-upload">Прикрепить</button></div>' +
      '<p class="muted">До 10 МБ каждый.</p>';
  }

  function avatars(list) {
    return '<div class="avatars">' + (list || []).slice(0, 5).map((a) =>
      '<span class="av" title="' + esc(a.username || a.first_name || "") + '">' +
      (a.photo_url ? '<img src="' + esc(a.photo_url) + '" alt="">' : esc((a.first_name || a.username || "?")[0])) +
      "</span>").join("") + "</div>";
  }

  function taskCard(t) {
    const overdue = t.deadline && t.status !== "done" && t.deadline < today();
    const color = overdue ? "#e5484d" : t.status === "done" ? "#30a46c" : "#3e63dd";
    return '<a class="card" style="border-left-color:' + color + '" href="#/tasks/' + t.id + '">' +
      '<div class="card-title">' + esc(t.title) + "</div>" +
      '<div class="chips">' +
      (t.deadline ? '<span class="chip' + (overdue ? " bad" : "") + '">📅 ' + esc(t.deadline) + "</span>" : "") +
      '<span class="chip">' + esc(STATUS_RU[t.status] || t.status) + "</span>" +
      (t.group_name ? '<span class="chip">👥 ' + esc(t.group_name) + "</span>" : "") +
      ((t.attachments && t.attachments.length) ? '<span class="chip">📎 ' + t.attachments.length + "</span>" : "") +
      "</div>" + avatars(t.assignees) + "</a>";
  }

  // Mobile-friendly people picker: tap chips instead of Ctrl+click multiselect.
  // Returns { get: () => number[] }. `initial` — array of tg_id.
  function peoplePicker(mount, users, initial) {
    const sel = new Set((initial || []).map(Number));
    mount.innerHTML =
      '<input class="pick-search" placeholder="Поиск по имени или нику…">' +
      '<div class="picks"></div><div class="muted pick-count"></div>';
    const list = mount.querySelector(".picks");
    const count = mount.querySelector(".pick-count");
    const search = mount.querySelector(".pick-search");
    function paint(filter) {
      const f = (filter || "").trim().toLowerCase();
      const shown = (users || []).filter((u) =>
        !f || (u.username || "").toLowerCase().includes(f) || (u.first_name || "").toLowerCase().includes(f));
      count.textContent = "Выбрано: " + sel.size;
      list.innerHTML = shown.map((u) => {
        const on = sel.has(Number(u.tg_id));
        return '<div class="pick' + (on ? " on" : "") + '" data-uid="' + u.tg_id + '">' +
          '<span class="av">' + (u.photo_url ? '<img src="' + esc(u.photo_url) + '">' : esc(((u.first_name || u.username || "?"))[0])) + "</span>" +
          '<span style="flex:1">@' + esc(u.username || u.tg_id) + " " + esc(u.first_name || "") + "</span>" +
          '<span class="pick-check">' + (on ? "✓" : "") + "</span></div>";
      }).join("") || '<p class="muted">Никого не найдено</p>';
      list.querySelectorAll(".pick").forEach((el) => {
        el.onclick = () => {
          const id = Number(el.dataset.uid);
          if (sel.has(id)) sel.delete(id); else sel.add(id);
          paint(search.value);
        };
      });
    }
    search.oninput = () => paint(search.value);
    paint("");
    return { get: () => [...sel] };
  }

  function navActive() {    const h = location.hash || "#/";
    document.querySelectorAll("[data-nav]").forEach((a) => {
      const href = a.getAttribute("href");
      a.classList.toggle("active", href === h || (href === "#/" && (h === "#/" || h === "")));
    });
  }

  // ---------- pages ----------
  async function pageProfile() {
    let me = tgUser();
    try { me = await api.me(); } catch (e) {}
    let tasks = [], groups = [];
    try { tasks = await api.tasks("?assignee=me"); } catch (e) {}
    try { groups = await api.groups(); } catch (e) {}
    const mine = (groups || []).filter((g) => (g.members || []).some((m) => me && m.tg_id === me.tg_id));
    app.innerHTML =
      '<div class="profile-head"><span class="av">' +
      (me && me.photo_url ? '<img src="' + esc(me.photo_url) + '">' : esc(((me && me.first_name) || "?")[0])) +
      "</span><div><div><b>" + esc((me && me.first_name) || "Профиль") + "</b></div>" +
      '<div class="muted">@' + esc((me && me.username) || "—") + "</div></div></div>" +
      "<h3>Мои задачи (" + tasks.length + ")</h3>" +
      (tasks.map(taskCard).join("") || '<p class="muted">Нет задач</p>') +
      "<h3>Мои группы</h3>" +
      (mine.map((g) => '<div class="card">👥 ' + esc(g.name) + " (" + g.members.length + ")</div>").join("") || '<p class="muted">Нет групп</p>');
  }

  const calState = { y: new Date().getFullYear(), m: new Date().getMonth(), scope: "me", gid: "", sel: today(), data: {}, groups: [] };
  function monthCells(y, m) {
    const startDay = (new Date(y, m, 1).getDay() + 6) % 7;
    const n = new Date(y, m + 1, 0).getDate();
    const cells = Array(startDay).fill(null);
    for (let d = 1; d <= n; d++) cells.push(y + "-" + String(m + 1).padStart(2, "0") + "-" + String(d).padStart(2, "0"));
    return cells;
  }
  async function pageCalendar() {
    try { calState.groups = await api.groups(); } catch (e) { calState.groups = []; }
    // Нормализуем gid: select даёт строку, бэкенд ждёт int.
    // Если выбранной группы уже нет в списке (удалена) — считаем, что ничего не выбрано.
    if (calState.scope === "group" && calState.gid !== "" && calState.gid != null) {
      const ok = (calState.groups || []).some((g) => String(g.id) === String(calState.gid));
      if (!ok) calState.gid = "";
    }
    const lastDay = new Date(calState.y, calState.m + 1, 0).getDate();
    const mm = String(calState.m + 1).padStart(2, "0");
    const from = calState.y + "-" + mm + "-01";
    const to = calState.y + "-" + mm + "-" + String(lastDay).padStart(2, "0");
    const gidNum = calState.gid !== "" && calState.gid != null ? Number(calState.gid) : 0;
    // scope=Группа: без выбора — задачи всех моих групп, с выбором — одной группы.
    let q = "?from=" + from + "&to=" + to + "&scope=" + calState.scope;
    if (calState.scope === "group" && gidNum) q += "&group_id=" + gidNum;
    let calErr = "";
    try { calState.data = await api.calendar(q); } catch (e) { calState.data = {}; calErr = String((e && e.message) || e); }
    // all tasks in the same scope (not only selected day / month).
    let allTasks = [];
    let allErr = "";
    {
      let allQ = "";
      if (calState.scope === "me") allQ = "?assignee=me";
      else if (calState.scope === "group") allQ = gidNum ? "?group_id=" + gidNum : "?scope=group";
      try { allTasks = allQ ? await api.tasks(allQ) : await api.tasks(); } catch (e) { allTasks = []; allErr = String((e && e.message) || e); }
    }
    const cells = monthCells(calState.y, calState.m);
    const gridCount = Object.keys(calState.data).reduce((n, k) => n + (calState.data[k] || []).length, 0);
    const ym = calState.y + "-" + String(calState.m + 1).padStart(2, "0");
    const selGroup = calState.scope === "group" && gidNum
      ? (calState.groups || []).find((g) => String(g.id) === String(gidNum))
      : null;
    app.innerHTML =
      "<h2>Календарь</h2>" +
      '<div class="tabs">' + ["me", "group", "all"].map((s) =>
        '<button data-cal-scope="' + s + '" class="' + (calState.scope === s ? "on" : "ghost") + '">' +
        (s === "me" ? "Мои" : s === "group" ? "Группа" : "Все") + "</button>").join("") + "</div>" +
      (calState.scope === "group"
        ? '<select id="cal-gid"><option value="">Все мои группы</option>' +
          calState.groups.map((g) => '<option value="' + g.id + '"' + (String(calState.gid) === String(g.id) ? " selected" : "") + ">" + esc(g.name) + "</option>").join("") + "</select>" +
          (selGroup ? '<p class="muted">Группа: ' + esc(selGroup.name) + " (id " + selGroup.id + ")</p>"
            : '<p class="muted">Показаны задачи всех твоих групп</p>') : "") +
      (calErr ? '<p class="muted">Ошибка календаря: ' + esc(calErr) + "</p>" : "") +
      (allErr ? '<p class="muted">Ошибка списка: ' + esc(allErr) + "</p>" : "") +
      '<div class="row"><button class="ghost" id="cal-prev">‹</button>' +
      '<b style="flex:1;text-align:center">' + ym + '</b><button class="ghost" id="cal-next">›</button></div>' +
      '<div class="cal-grid" style="margin-top:8px">' +
      cells.map((d) => {
        if (!d) return '<div class="cal-day"></div>';
        const list = calState.data[d] || [];
        return '<div class="cal-day' + (d === calState.sel ? " sel" : "") + '" data-day="' + d + '"><div>' + d.slice(8) + "</div>" +
          list.slice(0, 2).map((t) => '<span class="dot">' + esc(t.title.slice(0, 8)) + "</span>").join("") +
          (list.length > 2 ? "<div>+" + (list.length - 2) + "</div>" : "") + "</div>";
      }).join("") + "</div>" +
      "<h3>" + esc(calState.sel) + "</h3>" +
      (((calState.data[calState.sel] || []).map(taskCard).join("")) || '<p class="muted">Нет задач на этот день</p>') +
      "<h3>Все задачи (" + allTasks.length + ")</h3>" +
      ((gridCount > 0 && allTasks.length === 0 && !allErr)
        ? '<p class="muted">В сетке задачи есть, а в списке нет — жёстко обнови страницу (Ctrl+F5, в Telegram — очистить кэш), вероятно открылась старая версия приложения.</p>' : "") +
      (((allTasks.map(taskCard).join("")) || '<p class="muted">Нет задач</p>'));

    app.querySelectorAll("[data-cal-scope]").forEach((b) => b.onclick = () => { calState.scope = b.dataset.calScope; pageCalendar(); });
    const gidSel = document.getElementById("cal-gid");
    if (gidSel) gidSel.onchange = () => { calState.gid = gidSel.value; pageCalendar(); };
    document.getElementById("cal-prev").onclick = () => { if (calState.m === 0) { calState.y--; calState.m = 11; } else calState.m--; pageCalendar(); };
    document.getElementById("cal-next").onclick = () => { if (calState.m === 11) { calState.y++; calState.m = 0; } else calState.m++; pageCalendar(); };
    app.querySelectorAll("[data-day]").forEach((el) => el.onclick = () => { calState.sel = el.dataset.day; pageCalendar(); });
  }

  async function pageTaskNew() {
    let groups = [], users = [];
    try { groups = await api.groups(); } catch (e) {}
    try { users = await api.users(); } catch (e) {}
    app.innerHTML = "<h2>Новая задача</h2>" +
      '<input id="f-title" placeholder="Название *">' +
      '<textarea id="f-desc" placeholder="Описание"></textarea>' +
      '<input id="f-date" type="date">' +
      '<select id="f-status"><option value="new">Новая</option><option value="in_progress">В работе</option><option value="done">Готово</option></select>' +
      '<select id="f-group"><option value="">Без группы (только люди)</option>' +
      groups.map((g) => '<option value="' + g.id + '">' + esc(g.name) + "</option>").join("") + "</select>" +
      "<label>Исполнители (нажми, чтобы выбрать):</label>" +
      '<div id="f-pick"></div>' +
      "<label>Файлы (до 10 МБ каждый):</label>" +
      '<input id="f-files" type="file" multiple>' +
      '<button id="f-go" style="margin-top:8px;width:100%">Создать</button>';
    const picker = peoplePicker(document.getElementById("f-pick"), users, []);
    document.getElementById("f-go").onclick = async () => {
      const title = document.getElementById("f-title").value.trim();
      if (!title) return alert("Нужно название");
      const ids = picker.get();
      const t = await api.createTask({
        title, description: document.getElementById("f-desc").value,
        deadline: document.getElementById("f-date").value || null,
        status: document.getElementById("f-status").value,
        group_id: document.getElementById("f-group").value ? Number(document.getElementById("f-group").value) : null,
        assignee_ids: ids,
      });
      const files = document.getElementById("f-files").files || [];
      for (const f of files) {
        try { await uploadAttachment(t.id, f); }
        catch (e) { alert("Не загрузился файл " + f.name + ": " + e.message); }
      }
      location.hash = "#/tasks/" + t.id;
    };
  }

  async function pageTaskDetail(id) {
    let t, groups = [], users = [];
    try { t = await api.task(id); } catch (e) { app.innerHTML = "<p>Не найдено</p>"; return; }
    try { groups = await api.groups(); } catch (e) {}
    try { users = await api.users(); } catch (e) {}
    let edit = false;
    function view() {
      app.innerHTML = '<button class="ghost" id="b-back">‹ Назад</button><h2>' + esc(t.title) + "</h2>" +
        "<p>" + (esc(t.description) || '<span class="muted">Без описания</span>') + "</p>" +
        "<p>📅 " + esc(t.deadline || "—") + " · " + esc(STATUS_RU[t.status] || t.status) +
        (t.group_name ? " · 👥 " + esc(t.group_name) : "") + "</p>" +
        "<p>Исполнители: " + esc((t.assignees || []).map((a) => "@" + (a.username || a.tg_id)).join(", ") || "—") + "</p>" +
        (t.group_name ? '<p class="muted">Групповая задача: видна в фильтре группы «' + esc(t.group_name) + "». Чтобы убрать человека из задачи — сними галочку в редактировании.</p>" : "") +
        '<div class="row"><button id="b-edit">Редактировать</button><button class="danger" id="b-del">Удалить</button></div>' +
        attachmentsBlock(t);
      document.getElementById("b-back").onclick = () => history.back();
      document.getElementById("b-edit").onclick = () => { edit = true; form(); };
      document.getElementById("b-del").onclick = async () => { await api.deleteTask(id); location.hash = "#/"; };
      app.querySelectorAll("[data-del-file]").forEach((b) => b.onclick = async () => {
        if (!confirm("Удалить файл?")) return;
        await api.deleteAttachment(id, b.dataset.delFile);
        t = await api.task(id);
        view();
      });
      // Скачивание: в Telegram WebView программное сохранение blob игнорируется,
      // поэтому открываем файл во внешнем браузере через openLink (там работает).
      // initData едет query-параметром — заголовки через openLink не передать.
      // В обычном браузере качаем через fetch+blob без ухода со страницы.
      app.querySelectorAll("[data-dl-file]").forEach((a) => a.onclick = async (e) => {
        e.preventDefault();
        const fname = a.dataset.fname || "file";
        const base = a.getAttribute("href");
        if (tg && tg.openLink) {
          const url = base + (base.indexOf("?") >= 0 ? "&" : "?") + "initData=" + encodeURIComponent(initData());
          try { tg.openLink(url); } catch (err) { window.open(url, "_blank"); }
          return;
        }
        try {
          const r = await fetch(base, { headers: { "X-Telegram-Init-Data": initData() } });
          if (!r.ok) throw new Error(await r.text());
          const obj = URL.createObjectURL(await r.blob());
          const link = document.createElement("a");
          link.href = obj;
          link.download = fname;
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(obj), 5000);
        } catch (err) { alert("Не удалось скачать файл"); }
      });
      const upBtn = document.getElementById("f-upload");
      if (upBtn) upBtn.onclick = async () => {
        const inp = document.getElementById("f-file");
        const files = (inp && inp.files) || [];
        if (!files.length) return alert("Выбери файл");
        upBtn.disabled = true;
        try {
          for (const f of files) await uploadAttachment(id, f);
          t = await api.task(id);
          view();
        } catch (e) { alert("Ошибка загрузки: " + e.message); upBtn.disabled = false; }
      };
    }
    function form() {
      // Только прямые исполнители: открепление здесь реально убирает человека из задачи.
      // (Участники группы больше не подмешиваются в выбор — раньше снятие галочки
      // с участника группы ничего не меняло, т.к. он возвращался через группу.)
      const aids = (t.assignee_ids || (t.assignees || []).map((a) => a.tg_id) || []).map((x) => String(x));
      app.innerHTML = '<button class="ghost" id="b-back">‹ Назад</button><h2>Редактировать</h2>' +
        '<input id="e-title" value="' + esc(t.title) + '">' +
        '<textarea id="e-desc">' + esc(t.description || "") + "</textarea>" +
        '<input id="e-date" type="date" value="' + esc(t.deadline || "") + '">' +
        '<select id="e-status">' + Object.keys(STATUS_RU).map((s) => '<option value="' + s + '"' + (t.status === s ? " selected" : "") + ">" + STATUS_RU[s] + "</option>").join("") + "</select>" +
        '<select id="e-group"><option value="">Без группы</option>' +
        groups.map((g) => '<option value="' + g.id + '"' + (t.group_id === g.id ? " selected" : "") + ">" + esc(g.name) + "</option>").join("") + "</select>" +
        "<label>Исполнители (нажми, чтобы выбрать):</label>" +
        '<div id="e-pick"></div>' +
        '<div class="row" style="margin-top:8px"><button id="e-save">Сохранить</button><button class="ghost" id="e-cancel">Отмена</button></div>';
      const picker = peoplePicker(document.getElementById("e-pick"), users, aids);
      document.getElementById("b-back").onclick = () => { edit = false; view(); };
      document.getElementById("e-cancel").onclick = () => { edit = false; view(); };
      document.getElementById("e-save").onclick = async () => {
        const ids = picker.get();
        t = await api.patchTask(id, {
          title: document.getElementById("e-title").value,
          description: document.getElementById("e-desc").value,
          deadline: document.getElementById("e-date").value || null,
          status: document.getElementById("e-status").value,
          group_id: document.getElementById("e-group").value ? Number(document.getElementById("e-group").value) : null,
          assignee_ids: ids,
        });
        edit = false; view();
      };
    }
    view();
  }

  async function pageGroups() {
    let groups = [], users = [];
    try { groups = await api.groups(); } catch (e) {}
    try { users = await api.users(); } catch (e) {}
    app.innerHTML = "<h2>Группы</h2>" +
      '<div class="row"><input id="g-name" placeholder="Новая группа"><button id="g-add">+</button></div>' +
      groups.map((g) => {
        const memberIds = new Set((g.members || []).map((m) => Number(m.tg_id)));
        const candidates = (users || []).filter((u) => !memberIds.has(Number(u.tg_id)));
        return '<div class="card"><div class="row"><b style="flex:1">👥 ' + esc(g.name) + '</b><button class="danger" data-del="' + g.id + '">Удалить</button></div>' +
        (g.members || []).map((m) =>
          '<div class="row" style="margin-top:4px"><span style="flex:1">@' + esc(m.username || m.tg_id) + " " + esc(m.first_name || "") +
          '</span><button class="ghost" data-rm="' + g.id + ":" + m.tg_id + '">✕</button></div>').join("") +
        '<div class="row" style="margin-top:6px"><select data-sel="' + g.id + '"><option value="">Выбери человека…</option>' +
        candidates.map((u) => '<option value="' + u.tg_id + '">@' + esc(u.username || u.tg_id) + " " + esc(u.first_name || "") + "</option>").join("") +
        '</select><button data-plus="' + g.id + '">Добавить</button></div>' +
        '<div class="row" style="margin-top:6px"><input placeholder="@username или ID (если нет в списке)" data-inp="' + g.id + '"><button class="ghost" data-plus-id="' + g.id + '">+</button></div></div>';
      }).join("");
    document.getElementById("g-add").onclick = async () => {
      const v = document.getElementById("g-name").value.trim();
      if (v) { await api.createGroup(v); pageGroups(); }
    };
    app.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => { await api.deleteGroup(b.dataset.del); pageGroups(); });
    app.querySelectorAll("[data-rm]").forEach((b) => b.onclick = async () => {
      const parts = b.dataset.rm.split(":"); await api.removeMember(parts[0], parts[1]); pageGroups();
    });
    app.querySelectorAll("[data-plus]").forEach((b) => b.onclick = async () => {
      const gid = b.dataset.plus;
      const sel = app.querySelector('[data-sel="' + gid + '"]');
      if (!sel || !sel.value) return;
      await api.addMember(gid, { user_id: Number(sel.value) });
      pageGroups();
    });
    app.querySelectorAll("[data-plus-id]").forEach((b) => b.onclick = async () => {
      const gid = b.dataset.plusId;
      const inp = app.querySelector('[data-inp="' + gid + '"]');
      const v = (inp.value || "").trim();
      if (!v) return;
      await api.addMember(gid, /^\d+$/.test(v) ? { user_id: Number(v) } : { username: v });
      pageGroups();
    });
  }

  // ---------- router ----------
  async function route() {
    navActive();
    const h = location.hash || "#/";
    try {
      if (h === "#/" || h === "") await pageProfile();
      else if (h.startsWith("#/calendar")) await pageCalendar();
      else if (h === "#/tasks/new") await pageTaskNew();
      else if (h.startsWith("#/tasks/")) await pageTaskDetail(h.split("/")[2]);
      else if (h.startsWith("#/groups")) await pageGroups();
      else await pageProfile();
    } catch (e) {
      app.innerHTML = "<p>Ошибка: " + esc(e.message) + "</p>";
    }
    navActive();
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);
  route();
})();
