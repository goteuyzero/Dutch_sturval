const app = document.getElementById('app');
const toast = document.getElementById('toast');

const storage = {
  playerId: 'dutch_sturval_player_id',
  playerName: 'dutch_sturval_player_name',
  roomCode: 'dutch_sturval_room_code',
};

let state = null;
let socket = null;
let reconnectTimer = null;
let notesTimer = null;
let localNotesDraft = '';
let lastNotesFromServer = '';
let surrenderCountdownTimer = null;

function getPlayerId() {
  let id = localStorage.getItem(storage.playerId);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `p_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(storage.playerId, id);
  }
  return id;
}

function getStoredRoom() {
  return (localStorage.getItem(storage.roomCode) || '').trim();
}

function getStoredName() {
  return (localStorage.getItem(storage.playerName) || '').trim();
}

function setStoredSession(roomCode, name) {
  localStorage.setItem(storage.roomCode, roomCode);
  localStorage.setItem(storage.playerName, name);
}

function clearStoredRoom() {
  localStorage.removeItem(storage.roomCode);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function voteLabel(vote) {
  return {
    yes: 'Да',
    no: 'Нет',
    unknown: 'Не знаю',
    guessed: 'Угадал',
    surrender: 'Сдался',
    skip: 'Скип',
  }[vote] || '—';
}

function phaseLabel(phase) {
  return {
    lobby: 'Лобби',
    assigning: 'Загадываем персонажей',
    playing: 'Игра идет',
    game_over: 'Игра завершена',
  }[phase] || phase;
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove('hidden');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add('hidden'), 3200);
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || 'Ошибка запроса');
  }
  return data;
}

function connectSocket(roomCode) {
  if (socket) {
    socket.onclose = null;
    socket.close();
  }
  clearTimeout(reconnectTimer);

  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const playerId = getPlayerId();
  socket = new WebSocket(`${protocol}://${location.host}/ws/${encodeURIComponent(roomCode)}/${encodeURIComponent(playerId)}`);

  socket.onmessage = (event) => {
    state = JSON.parse(event.data);
    render();
  };

  socket.onclose = () => {
    if (getStoredRoom()) {
      reconnectTimer = setTimeout(() => connectSocket(getStoredRoom()), 1200);
    }
  };
}

async function createRoom() {
  const name = document.getElementById('nameInput')?.value.trim();
  if (!name) return showToast('Введи имя');
  try {
    const data = await api('/api/create-room', { player_id: getPlayerId(), name });
    setStoredSession(data.room_code, name);
    connectSocket(data.room_code);
  } catch (err) {
    showToast(err.message);
  }
}

async function joinRoom() {
  const name = document.getElementById('nameInput')?.value.trim();
  const code = document.getElementById('roomInput')?.value.trim();
  if (!name) return showToast('Введи имя');
  if (!code) return showToast('Введи код комнаты');
  try {
    const data = await api('/api/join-room', { player_id: getPlayerId(), name, room_code: code });
    setStoredSession(data.room_code, name);
    connectSocket(data.room_code);
  } catch (err) {
    showToast(err.message);
  }
}

async function restoreRoom() {
  const name = getStoredName();
  const code = getStoredRoom();
  if (!name || !code) return;
  try {
    const data = await api('/api/join-room', { player_id: getPlayerId(), name, room_code: code });
    setStoredSession(data.room_code, name);
    connectSocket(data.room_code);
  } catch (err) {
    clearStoredRoom();
    showToast('Не удалось восстановить комнату. Возможно, сервер перезапускался.');
    renderLanding();
  }
}

async function action(path, payload = {}) {
  if (!state) return;
  try {
    await api(`/api/room/${state.room_code}${path}`, { player_id: getPlayerId(), ...payload });
  } catch (err) {
    showToast(err.message);
  }
}

function leaveRoomLocal() {
  clearStoredRoom();
  state = null;
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
  renderLanding();
}

function render() {
  if (!state || !state.me) {
    renderLanding();
    return;
  }

  app.innerHTML = `
    <div class="game-shell">
      ${renderSidebar()}
      ${renderMain()}
      ${renderNotes()}
    </div>
  `;

  attachNotesHandlers();
  attachCharacterFormHandler();
  startSurrenderTimerIfNeeded();
}

function renderLanding() {
  const storedName = getStoredName();
  const storedRoom = getStoredRoom();
  const urlRoom = new URLSearchParams(location.search).get('room') || '';

  app.innerHTML = `
    <div class="landing-bg">
      <div class="landing-card">
        <div class="landing-title">Голландский<br>штурвал</div>
        <label class="field-label">Твоё имя</label>
        <input id="nameInput" class="input" maxlength="40" value="${escapeHtml(storedName)}" />

        <div class="landing-actions">
          <button class="btn btn-green" onclick="createRoom()">Создать лобби</button>
        </div>

        <div class="divider">или</div>

        <label class="field-label">Код комнаты</label>
        <input id="roomInput" class="input code-input" maxlength="4" value="${escapeHtml(urlRoom || storedRoom)}" />
        <button class="btn btn-green full landing-join-btn" onclick="joinRoom()">Подключиться</button>

        ${storedRoom && storedName ? `
          <button class="link-button" onclick="restoreRoom()">Вернуться в комнату ${escapeHtml(storedRoom)}</button>
        ` : ''}
      </div>
    </div>
  `;
}

function renderSidebar() {
  const me = state.me;
  return `
    <aside class="sidebar">
      <div class="brand">Голландский<br>штурвал</div>
      <div class="room-code">Комната #${escapeHtml(state.room_code)}</div>
      <div class="small-muted">${escapeHtml(phaseLabel(state.phase))} · Игра ${state.game_number || 0}</div>

      <div class="me-card">
        <div class="me-name">${escapeHtml(me.name)} ${me.is_host ? '<span class="host-badge">хост</span>' : ''}</div>
        <div class="small-muted">Очки: ${me.total_score}</div>
        ${me.target_name ? `<div class="relation">Ты загадываешь: <b>${escapeHtml(me.target_name)}</b></div>` : ''}
        ${me.giver_name ? `<div class="relation">Тебе загадывает: <b>${escapeHtml(me.giver_name)}</b></div>` : ''}
      </div>

      <div class="players-title">Игроки в порядке хода</div>
      <div class="players-list">
        ${state.players.map(renderPlayerRow).join('')}
      </div>

      <div class="sidebar-actions">
        ${state.phase === 'lobby' ? renderReadyControls() : ''}
        ${state.can_surrender ? renderSurrenderButton() : ''}
        <button class="btn btn-muted full" onclick="leaveRoomLocal()">Выйти локально</button>
      </div>

      ${state.me.is_host ? renderAdminPanel() : ''}
    </aside>
  `;
}

function renderPlayerRow(player) {
  const status = playerStatus(player);
  const activeClass = player.is_active ? ' active' : '';
  const character = player.character_set
    ? (player.character_visible ? player.character : 'скрыт')
    : 'не задан';

  return `
    <div class="player-row${activeClass}">
      <span class="status-dot ${status.className}"></span>
      <div class="player-row-main">
        <div class="player-name-line">
          <span>${escapeHtml(player.name)}</span>
          ${player.is_host ? '<span class="mini-badge">H</span>' : ''}
        </div>
        <div class="player-subline">${escapeHtml(status.label)} · ${escapeHtml(character)} · ${player.total_score} очк.</div>
      </div>
    </div>
  `;
}

function playerStatus(player) {
  if (!player.connected) return { className: 'gray', label: 'оффлайн' };
  if (player.is_active) return { className: 'yellow', label: 'ходит' };
  if (player.guessed) return { className: 'green', label: 'угадал' };
  if (player.surrendered) return { className: 'pink', label: 'сдался' };
  if (player.queue_removed) return { className: 'gray', label: 'вне очереди' };
  if (state.phase === 'lobby') return player.ready ? { className: 'green', label: 'ready' } : { className: 'gray', label: 'не ready' };
  return { className: 'green-soft', label: 'в игре' };
}

function renderReadyControls() {
  const me = state.me;
  return `
    <button class="btn ${me.ready ? 'btn-light' : 'btn-green'} full" onclick="action('/ready', { ready: ${!me.ready} })">
      ${me.ready ? 'Снять ready' : 'Ready'}
    </button>
    ${me.is_host ? `
      <button class="btn btn-yellow full" ${state.can_start ? '' : 'disabled'} onclick="action('/start')">
        Старт
      </button>
      <div class="small-muted">Старт доступен, когда все нажали ready.</div>
    ` : `<div class="small-muted">Ждем, пока хост начнет игру.</div>`}
  `;
}

function renderSurrenderButton() {
  const pending = state.me.surrender_pending;
  const seconds = state.me.surrender_seconds_left || 0;
  return `
    <button class="btn btn-danger full" ${pending && seconds > 0 ? 'disabled' : ''} onclick="action('/surrender')">
      ${pending ? (seconds > 0 ? `Сдаться через ${seconds}` : 'Подтвердить сдачу') : 'Сдаться'}
    </button>
  `;
}

function renderAdminPanel() {
  const playerButtons = state.players
    .filter(player => player.id !== state.me.id)
    .map(player => `
      <div class="admin-player-row">
        <span>${escapeHtml(player.name)}</span>
        <div>
          <button class="tiny-btn" onclick="adminRemoveFromQueue('${player.id}')">Вне очереди</button>
          <button class="tiny-btn danger" onclick="adminKick('${player.id}', '${escapeHtml(player.name)}')">Кик</button>
        </div>
      </div>
    `).join('');

  return `
    <details class="admin-panel">
      <summary>Панель хоста</summary>
      <div class="admin-block">
        <button class="btn btn-light full" onclick="action('/admin/skip-turn')" ${state.phase === 'playing' ? '' : 'disabled'}>Передать ход</button>
        <div class="admin-force-grid">
          <button class="tiny-btn green" onclick="action('/admin/force-answer', { answer: 'yes' })" ${state.phase === 'playing' ? '' : 'disabled'}>Да</button>
          <button class="tiny-btn" onclick="action('/admin/force-answer', { answer: 'unknown' })" ${state.phase === 'playing' ? '' : 'disabled'}>Не знаю</button>
          <button class="tiny-btn danger" onclick="action('/admin/force-answer', { answer: 'no' })" ${state.phase === 'playing' ? '' : 'disabled'}>Нет</button>
        </div>
        <div class="small-muted">Принудительный ответ игнорирует текущее голосование.</div>
      </div>
      <div class="admin-block">
        ${playerButtons || '<div class="small-muted">Нет других игроков.</div>'}
      </div>
    </details>
  `;
}

function adminKick(playerId, name) {
  if (confirm(`Удалить игрока ${name} из игры полностью?`)) {
    action('/admin/kick-player', { target_id: playerId });
  }
}

function adminRemoveFromQueue(playerId) {
  action('/admin/remove-from-queue', { target_id: playerId });
}

function renderMain() {
  if (state.phase === 'lobby') return renderLobbyMain();
  if (state.phase === 'assigning') return renderAssigningMain();
  if (state.phase === 'playing') return renderPlayingMain();
  if (state.phase === 'game_over') return renderGameOverMain();
  return `<main class="main-panel"><div class="card">Неизвестное состояние игры.</div></main>`;
}

function renderLobbyMain() {
  return `
    <main class="main-panel">
      <div class="center-card">
        <div class="big-title">Лобби</div>
        <div class="subtitle">Код комнаты: <b>${escapeHtml(state.room_code)}</b></div>
        <div class="copy-row">
          <input class="input" readonly value="${escapeHtml(location.origin + '?room=' + state.room_code)}" />
          <button class="btn btn-light" onclick="copyInviteLink()">Скопировать ссылку</button>
        </div>
        <div class="lobby-status">${state.all_ready ? 'Все готовы. Хост может начинать.' : 'Ждем ready от всех игроков.'}</div>
      </div>
      ${renderTurnDots()}
    </main>
  `;
}

function copyInviteLink() {
  navigator.clipboard?.writeText(`${location.origin}?room=${state.room_code}`);
  showToast('Ссылка скопирована');
}

function renderAssigningMain() {
  const me = state.me;
  const targetName = me.target_name || 'игрок не назначен';
  const targetPlayer = state.players.find(p => p.id === me.target_id);
  const alreadySet = targetPlayer?.character_set;

  return `
    <main class="main-panel">
      <div class="center-card wide">
        <div class="big-title">Загадай персонажа</div>
        <div class="subtitle">Ты загадываешь персонажа для:</div>
        <div class="target-name">${escapeHtml(targetName)}</div>
        <form id="characterForm" class="character-form">
          <input id="characterInput" class="input character-input" maxlength="80" value="${alreadySet && targetPlayer.character_visible ? escapeHtml(targetPlayer.character) : ''}" />
          <button class="btn btn-yellow" type="submit">Сохранить</button>
        </form>
        <div class="small-muted">Игра начнется автоматически, когда все зададут персонажей.</div>
      </div>

      <div class="assignment-grid">
        ${state.players.map(player => `
          <div class="assignment-card ${player.character_set ? 'done' : ''}">
            <div>${escapeHtml(player.name)}</div>
            <span>${player.character_set ? 'персонаж задан' : 'ждет персонажа'}</span>
          </div>
        `).join('')}
      </div>
      ${renderTurnDots()}
    </main>
  `;
}

function attachCharacterFormHandler() {
  const form = document.getElementById('characterForm');
  if (!form || !state?.me?.target_id) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const character = document.getElementById('characterInput').value.trim();
    if (!character) return showToast('Введи персонажа');
    await action('/set-character', { target_id: state.me.target_id, character });
  });
}

function renderPlayingMain() {
  const isMyTurn = state.active_player_id === state.me.id;
  const characterText = state.active_character_visible ? state.active_character : '(Персонаж)';
  const activePlayer = state.players.find(p => p.id === state.active_player_id);

  return `
    <main class="main-panel">
      <div class="round-info">
        <div class="last-event">${escapeHtml(state.last_event || 'Игра идет.')}</div>
        ${state.last_answer ? `<div class="last-answer">Последний итог: ${escapeHtml(voteLabel(state.last_answer))}</div>` : ''}
      </div>

      <section class="question-card">
        <div class="active-name">${escapeHtml(state.active_player_name || '—')}</div>
        <div class="active-character">${escapeHtml(characterText)}</div>
        <div class="turn-hint">
          ${isMyTurn ? 'Твой ход. Задавай вопросы голосом в Discord. Ты не голосуешь.' : `Сейчас вопросы задает ${escapeHtml(state.active_player_name || 'игрок')}.`}
        </div>

        <div class="vote-controls">
          ${renderVoteButton('yes', 'Да', 'btn-green')}
          ${renderVoteButton('unknown', 'Не знаю', 'btn-light')}
          ${renderVoteButton('no', 'Нет', 'btn-pink')}
        </div>

        <div class="vote-summary">
          <span>Да: ${state.votes.yes}</span>
          <span>Не знаю: ${state.votes.unknown}</span>
          <span>Нет: ${state.votes.no}</span>
          <span>Осталось голосов: ${state.votes.remaining}</span>
          <span>Для перехода хода нужно «нет»: ${state.votes.no_needed_to_end_turn}</span>
        </div>

        <div class="game-actions">
          ${state.can_confirm_guessed ? `<button class="btn btn-yellow" onclick="action('/confirm-guessed')">Угадал</button>` : ''}
          ${activePlayer?.giver_name ? `<div class="small-muted">Подтвердить угадывание может: ${escapeHtml(activePlayer.giver_name)} или хост.</div>` : ''}
        </div>
      </section>
      ${renderTurnDots()}
    </main>
  `;
}

function renderVoteButton(vote, label, className) {
  const disabled = !state.can_vote;
  const voted = state.my_vote === vote;
  return `
    <button class="btn ${className} vote-btn ${voted ? 'selected' : ''}" ${disabled ? 'disabled' : ''} onclick="action('/vote', { vote: '${vote}' })">
      ${label}
    </button>
  `;
}

function renderGameOverMain() {
  const sortedPlayers = [...state.players].sort((a, b) => {
    const scoreDiff = (b.round_score || 0) - (a.round_score || 0);
    if (scoreDiff !== 0) return scoreDiff;
    return (b.total_score || 0) - (a.total_score || 0);
  });

  return `
    <main class="main-panel">
      <div class="center-card wide">
        <div class="big-title">Игра завершена</div>
        <div class="subtitle">Очки за эту игру уже добавлены к общему счету.</div>
        <div class="results-table">
          <div class="results-head"><span>Игрок</span><span>Персонаж</span><span>Раунд</span><span>Всего</span></div>
          ${sortedPlayers.map(player => `
            <div class="results-row">
              <span>${escapeHtml(player.name)}</span>
              <span>${escapeHtml(player.character || '—')}</span>
              <span>${player.round_score || 0}</span>
              <span>${player.total_score}</span>
            </div>
          `).join('')}
        </div>
        ${state.me.is_host ? `<button class="btn btn-yellow" onclick="action('/new-game')">Новая игра</button>` : '<div class="small-muted">Новую игру запускает хост.</div>'}
      </div>
      ${renderTurnDots()}
    </main>
  `;
}

function renderTurnDots() {
  if (!state.players.length) return '';
  return `
    <div class="turn-dots">
      ${state.players.map(player => {
        const status = playerStatus(player);
        return `<span class="turn-dot ${status.className} ${player.is_active ? 'active' : ''}" title="${escapeHtml(player.name)}"></span>`;
      }).join('')}
    </div>
  `;
}

function renderNotes() {
  const notes = state.me?.notes || '';
  const noteValue = document.activeElement?.id === 'notesArea' ? localNotesDraft : notes;
  return `
    <aside class="notes-panel">
      <div class="notes-title">Поле для заметок</div>
      <textarea id="notesArea" class="notes-area">${escapeHtml(noteValue)}</textarea>
    </aside>
  `;
}

function attachNotesHandlers() {
  const area = document.getElementById('notesArea');
  if (!area || !state?.me) return;

  if (document.activeElement !== area && state.me.notes !== lastNotesFromServer) {
    area.value = state.me.notes || '';
    lastNotesFromServer = state.me.notes || '';
    localNotesDraft = area.value;
  }

  area.addEventListener('input', () => {
    localNotesDraft = area.value;
    clearTimeout(notesTimer);
    notesTimer = setTimeout(() => {
      action('/notes', { notes: localNotesDraft });
    }, 500);
  });
}

function startSurrenderTimerIfNeeded() {
  clearInterval(surrenderCountdownTimer);
  if (state?.me?.surrender_pending && state.me.surrender_seconds_left > 0) {
    surrenderCountdownTimer = setInterval(() => {
      if (state && state.me) {
        state.me.surrender_seconds_left = Math.max(0, state.me.surrender_seconds_left - 1);
        render();
      }
    }, 1000);
  }
}

window.createRoom = createRoom;
window.joinRoom = joinRoom;
window.restoreRoom = restoreRoom;
window.action = action;
window.leaveRoomLocal = leaveRoomLocal;
window.copyInviteLink = copyInviteLink;
window.adminKick = adminKick;
window.adminRemoveFromQueue = adminRemoveFromQueue;

renderLanding();

if (getStoredRoom() && getStoredName()) {
  restoreRoom();
}
