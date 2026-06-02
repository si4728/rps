const choiceNames = { rock: "바위", paper: "보", scissors: "가위", none: "미선택" };
const resultNames = { win: "승", lose: "패", draw: "무" };

let currentMatchId = null;
let lastInviteFrom = null;
let pollBusy = false;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}

function setStatus(text) {
  $("status").textContent = text;
}

function setChoiceEnabled(enabled) {
  document.querySelectorAll(".choice").forEach((btn) => {
    btn.disabled = !enabled;
  });
}

function setMatchState(match) {
  if (!match) {
    currentMatchId = null;
    $("matchInfo").textContent = "아직 매칭되지 않았습니다.";
    $("choiceStatus").textContent = "선택 대기";
    $("timer").textContent = "-";
    $("btnJoin").disabled = false;
    setChoiceEnabled(false);
    return;
  }

  currentMatchId = match.game_id || match.match_id;
  $("matchInfo").textContent = `게임 #${match.game_id || match.match_id} / 상대: ${match.opponent.name} (#${match.opponent.id})`;
  $("timer").textContent = String(match.timer_left);
  $("btnJoin").disabled = true;

  if (match.choice_submitted) {
    $("choiceStatus").textContent = `라운드 ${match.round_no}: 내 선택 완료. 상대를 기다리는 중입니다.`;
    setChoiceEnabled(false);
  } else {
    $("choiceStatus").textContent = `라운드 ${match.round_no}: 선택해 주세요.`;
    setChoiceEnabled(true);
  }
}

function handleEvents(events) {
  for (const msg of events || []) {
    switch (msg.event) {
      case "matched":
        setStatus(`매칭 완료. 게임 ID: ${msg.game_id || msg.match_id} / 상대: ${msg.opponent?.name || "-"}`);
        break;
      case "result":
        renderResult(msg);
        setStatus("결과가 나왔습니다. 다음 라운드를 진행하세요.");
        break;
      case "match_ended":
        setStatus("매치가 종료되었습니다.");
        $("resultBox").textContent = "-";
        break;
      case "invited":
        handleInvite(msg.from);
        break;
      case "invite_declined":
        setStatus("초청이 거절되었습니다.");
        break;
    }
  }
}

async function handleInvite(from) {
  if (!from?.user_id || lastInviteFrom === from.user_id) return;
  lastInviteFrom = from.user_id;
  const accepted = window.confirm(`${from.name} 님의 초청을 수락할까요?`);
  try {
    await api("/api/match/invite/respond", {
      method: "POST",
      body: JSON.stringify({ from_user_id: from.user_id, accepted }),
    });
    setStatus(accepted ? "초청을 수락했습니다." : "초청을 거절했습니다.");
  } catch (err) {
    setStatus(`초청 응답 실패: ${err.message}`);
  } finally {
    lastInviteFrom = null;
  }
}

function renderResult(r) {
  const p1 = r.p1 || {};
  const p2 = r.p2 || {};
  const meIsP1 = p1.id === USER_ID;
  const me = meIsP1 ? p1 : p2;
  const opp = meIsP1 ? p2 : p1;

  let outcome = "무";
  if (r.winner_id === USER_ID) outcome = "승";
  if (r.winner_id && r.winner_id !== USER_ID) outcome = "패";

  $("resultBox").textContent = [
    `라운드 ${r.round_no}: ${outcome}`,
    `내 선택: ${choiceNames[me.choice] || me.choice}`,
    `상대 선택: ${choiceNames[opp.choice] || opp.choice}`,
    `상대: ${opp.name || "-"} (${opp.id || "-"})`,
    r.note ? `비고: ${r.note}` : "",
  ].filter(Boolean).join("\n");
}

async function loadState() {
  const data = await api("/api/state");
  const room = data.user.room_id ? `#${data.user.room_id}` : "(없음)";
  $("roomInfo").textContent = `현재 방: ${room} / 상태: ${data.user.status}`;
  setMatchState(data.match);

  if (data.invites?.length) {
    for (const invite of data.invites) {
      await handleInvite({ user_id: invite.from_user_id, name: invite.from_name });
    }
  }

  handleEvents(data.events);
}

async function loadRooms() {
  const data = await api("/api/rooms");
  const select = $("roomSelect");
  const selected = select.value;
  select.innerHTML = `<option value="">방 선택</option>` + data.items
    .map((r) => `<option value="${r.room_id}">${escapeHtml(r.room_name)} (#${r.room_id})</option>`)
    .join("");
  if (selected) select.value = selected;
}

async function loadOnlineUsers() {
  const data = await api("/api/online");
  const select = $("inviteSelect");
  select.innerHTML = data.items.length
    ? data.items.map((u) => `<option value="${u.user_id}">${escapeHtml(u.name)} (#${u.user_id})</option>`).join("")
    : `<option value="">초청 가능한 사용자 없음</option>`;
  $("btnInvite").disabled = data.items.length === 0;
}

async function loadStats() {
  const data = await api("/api/stats");
  const s = data.stats;
  $("statWin").textContent = s.win;
  $("statLose").textContent = s.lose;
  $("statDraw").textContent = s.draw;
  $("statRate").textContent = `${s.win_rate}%`;
}

async function loadAnalysis() {
  const data = await api("/api/analysis");
  const a = data.analysis;
  $("analysisTotal").textContent = a.summary.total;
  $("analysisRecentRate").textContent = `${a.recent_record.win_rate}%`;
  $("analysisFavorite").textContent = choiceNames[a.favorite_choice] || "-";
  $("analysisBest").textContent = choiceNames[a.best_choice] || "-";

  const insights = $("analysisInsights");
  insights.innerHTML = a.insights.map((text) => `<li>${escapeHtml(text)}</li>`).join("");

  const tbody = $("choiceAnalysisTable").querySelector("tbody");
  tbody.innerHTML = Object.entries(a.choices).map(([choice, record]) => `
    <tr>
      <td>${choiceNames[choice] || choice}</td>
      <td>${record.win}</td>
      <td>${record.lose}</td>
      <td>${record.draw}</td>
      <td>${record.win_rate}%</td>
    </tr>
  `).join("");
}

async function loadRanking() {
  const data = await api("/api/ranking?limit=20");
  const tbody = $("rankingTable").querySelector("tbody");
  tbody.innerHTML = data.items.map((u, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${escapeHtml(u.name)} (#${u.user_id})</td>
      <td>${u.win}</td>
      <td>${u.lose}</td>
      <td>${u.draw}</td>
      <td>${u.win_rate}%</td>
    </tr>
  `).join("");
}

async function loadHistory() {
  const data = await api("/api/history");
  const tbody = $("historyTable").querySelector("tbody");
  tbody.innerHTML = data.items.map((r) => `
    <tr>
      <td>${new Date(r.played_at).toLocaleString()}</td>
      <td>${escapeHtml(r.opponent_name)} (#${r.opponent_id})</td>
      <td>${choiceNames[r.my_choice] || r.my_choice}</td>
      <td>${choiceNames[r.opp_choice] || r.opp_choice}</td>
      <td>${resultNames[r.result] || r.result}</td>
    </tr>
  `).join("");
}

async function refreshAll() {
  if (pollBusy) return;
  pollBusy = true;
  try {
    await Promise.allSettled([
      loadState(),
      loadRooms(),
      loadOnlineUsers(),
      loadStats(),
      loadAnalysis(),
      loadRanking(),
      loadHistory(),
    ]);
  } finally {
    pollBusy = false;
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

function bindUI() {
  $("btnJoin").addEventListener("click", async () => {
    try {
      await api("/api/match/join", { method: "POST", body: "{}" });
      setStatus("대기열에 등록되었습니다. 상대를 기다리는 중입니다.");
      $("btnJoin").disabled = true;
      await refreshAll();
    } catch (err) {
      setStatus(`매칭 실패: ${err.message}`);
    }
  });

  $("btnEndMatch").addEventListener("click", async () => {
    try {
      await api("/api/match/end", { method: "POST", body: "{}" });
      await refreshAll();
    } catch (err) {
      setStatus(`종료 실패: ${err.message}`);
    }
  });

  $("btnReset").addEventListener("click", () => location.reload());

  $("btnInvite").addEventListener("click", async () => {
    const toUserId = Number($("inviteSelect").value);
    if (!toUserId) return;
    try {
      await api("/api/match/invite", { method: "POST", body: JSON.stringify({ to_user_id: toUserId }) });
      setStatus("초청을 보냈습니다.");
    } catch (err) {
      setStatus(`초청 실패: ${err.message}`);
    }
  });

  $("btnCreateRoom").addEventListener("click", async () => {
    const roomName = $("roomName").value.trim();
    if (!roomName) return;
    try {
      await api("/api/rooms", { method: "POST", body: JSON.stringify({ room_name: roomName }) });
      $("roomName").value = "";
      await refreshAll();
    } catch (err) {
      setStatus(`방 생성 실패: ${err.message}`);
    }
  });

  $("btnJoinRoom").addEventListener("click", async () => {
    const roomId = Number($("roomSelect").value);
    if (!roomId) return;
    try {
      await api("/api/rooms/join", { method: "POST", body: JSON.stringify({ room_id: roomId }) });
      await refreshAll();
    } catch (err) {
      setStatus(`방 참가 실패: ${err.message}`);
    }
  });

  $("btnLeaveRoom").addEventListener("click", async () => {
    try {
      await api("/api/rooms/leave", { method: "POST", body: "{}" });
      await refreshAll();
    } catch (err) {
      setStatus(`방 나가기 실패: ${err.message}`);
    }
  });

  document.querySelectorAll(".choice").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api("/api/match/choice", { method: "POST", body: JSON.stringify({ choice: btn.dataset.choice }) });
        $("choiceStatus").textContent = `${btn.textContent} 선택 완료. 상대를 기다리는 중입니다.`;
        setChoiceEnabled(false);
        await refreshAll();
      } catch (err) {
        setStatus(`선택 실패: ${err.message}`);
      }
    });
  });
}

window.addEventListener("load", () => {
  bindUI();
  setChoiceEnabled(false);
  setStatus("서버에 연결되었습니다.");
  refreshAll();
  window.setInterval(refreshAll, 1000);
});
