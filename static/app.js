let tzReady = false;

async function ensureTz() {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone; // e.g. "Asia/Seoul"
    const r = await fetch('/api/tz', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ tz })
    });
    return r.ok;
  } catch(e) {
    return false;
  }
}

async function ensureTzOnce() {
  if (tzReady) return;
  const ok = await ensureTz();
  if (ok) tzReady = true;
}

function renderCtl(type, isActive) {
  const el = document.getElementById(type + '_ctl');
  if (!el) return;

  if (isActive) {
    el.innerHTML = `
      <button class="btnGhost btnIcon"
              onclick="confirmCancelModal('${type}')"
              title="타이머 정지" aria-label="타이머 정지">
        <img src="/static/icon_stop.svg" alt="stop">
      </button>
    `;
  } else {
    el.innerHTML = `
      <button class="btnPrimary btnIcon"
              onclick="startTimer('${type}')"
              title="타이머 시작"
              aria-label="타이머 시작">
        <img src="/static/icon_play.svg" alt="play">
      </button>
    `;
  }
}

function openFeedback() {
  window.open(
    'https://docs.google.com/forms/d/1ht8IpW7Mm4tuScg8JVVQ4cDkU4tcQ1NO5RQ7groAOps',
    '_blank',
    'noopener'
  );
}

function humanizeSeconds(sec) {
  if (sec <= 0) return "0분";
  const m = Math.floor(sec / 60);
  const h = Math.floor(m / 60);
  const mm = m % 60;
  if (h <= 0) return `${mm}분`;
  return `${h}시간 ${mm}분`;
}

function showWarn(html) {
  const box = document.getElementById('dmWarn');
  box.innerHTML = html;
  box.style.display = 'block';
}

function hideWarn() {
  const box = document.getElementById('dmWarn');
  box.style.display = 'none';
}

async function openExternal(kind) {
  try {
    await fetch('/api/ack/' + kind, { method: 'POST' });
  } catch(e) {}

  window.open('/out/invite', '_blank', 'noopener');

  const started = Date.now();
  const limitMs = 60 * 1000;

  const timer = setInterval(async () => {
    try {
      const r = await fetch('/api/banner', { cache: 'no-store' });
      if(!r.ok) return;
      const s = await r.json();

      if(s && s.show_banner === false) {
        clearInterval(timer);
        const el = document.getElementById('bannerWrap');
        if(el) el.innerHTML = '';
        try { await refreshStatus(); } catch(e) {}
      }
    } catch(e) {}

    if(Date.now() - started > limitMs) {
      clearInterval(timer);
    }
  }, 800);
}

async function startTimer(type) {
  const r = await fetch('/api/timer/' + type, {method:'POST'});
  if (r.status === 401) { showLoginRequired(); return; }
  const t = await r.text();
  document.getElementById('hint').textContent = t.replaceAll('\n','  ');
  await refreshStatus();
}

async function cancelTimer(type) {
  const r = await fetch('/api/timer/' + type + '/cancel', {method:'POST'});
  if (r.status === 401) { showLoginRequired(); return; }
  const t = await r.text();
  document.getElementById('hint').textContent = t.replaceAll('\n','  ');
  await refreshStatus();
}

let pendingCancelType = null;

function timerLabel(type) {
  return type === 'rudolph' ? '루돌프 코 (3시간)' : '반창고 (1시간)';
}

function confirmCancelModal(type) {
  pendingCancelType = type;

  const titleEl = document.getElementById('confirmTitle');
  const descEl = document.getElementById('confirmDesc');
  const okBtn = document.getElementById('confirmOkBtn');

  if (titleEl) titleEl.textContent = `${timerLabel(type)} 타이머를 정지할까요?`;
  if (descEl) descEl.innerHTML =
    `정지하면 <b>현재 남은 시간</b>과 <b>설정 정보</b>가 모두 삭제됩니다.`;

  if (okBtn) {
    okBtn.onclick = async () => {
      const t = pendingCancelType;
      pendingCancelType = null;
      closeConfirm();
      if (t) await cancelTimer(t);
    };
  }

  const bg = document.getElementById('confirmBg');
  if (bg) bg.style.display = 'flex';
}

function closeConfirm(e) {
  if (e && e.target && e.target.id !== 'confirmBg') return;
  const bg = document.getElementById('confirmBg');
  if (bg) bg.style.display = 'none';
  pendingCancelType = null;
}

let testDmAttempted = false;

async function testSend(){
  testDmAttempted = true;

  const r = await fetch('/api/test-send', {method:'POST'});
  if (r.status === 401) { showLoginRequired(); return; }

  if (!r.ok) {
     showWarn(`
      <b>테스트 DM을 성공적으로 보낼 수 없어요😢</b><br/>
      위의 <b>“봇 초대하기 → 테스트 DM”</b> 버튼을 다시 눌러주세요.
      `);
  } else {
       hideWarn();
       document.getElementById('hint').textContent =
         '✅ 테스트 DM이 성공적으로 도착했어요!';
  }
}

function showLoginRequired() {
  showWarn(`
    <b>알림을 받기 위해 로그인이 필요합니다.</b><br/>
    오른쪽 상단의 디스코드로 로그인 버튼을 눌러주세요.
  `);

  // 상태 UI도 초기화
  document.getElementById('rudolph_left').textContent = '-';
  document.getElementById('bandage_left').textContent = '-';
  document.getElementById('rudolph_line').textContent = '로그인 후 확인 가능';
  document.getElementById('bandage_line').textContent = '로그인 후 확인 가능';
  document.getElementById('rudolph_bar').style.width = "0%";
  document.getElementById('bandage_bar').style.width = "0%";
}

async function fetchStatus() {
  const r = await fetch('/api/status.json', { cache: 'no-store' });

  // 로그인 필요(401)면: JSON(detail) 찍지 않고 UI 안내로 처리
  if (r.status == 401) {
    showLoginRequired();
    return null;
  }

  if(!r.ok) {
    const t = await r.text().catch(() => '');
    showWarn(`<b>상태를 불러오지 못했어요.</b><br/><span class="mono">${t}</span>`);
    return null;
  }

  hideWarn();
  return await r.json();
}

async function fetchDmHealth() {
  const r = await fetch('/api/dm/health', { cache: 'no-store' });
  if (r.status === 401) { showLoginRequired(); return null; }
  if(!r.ok) return null;
  return await r.json();
}

function calc(timer, serverNowIso, totalSec) {
  if(!timer || timer.status !== 'scheduled') {
    return { active:false, leftText:"설정 없음", dueLocal:"-", setLocal:"-", pct:0 };
  }
  const now = new Date(serverNowIso);
  const due = new Date(timer.due_at);

  const leftSec = Math.floor((due - now) / 1000);
  const elapsed = totalSec - leftSec;
  const pct = Math.max(0, Math.min(100, (elapsed / totalSec) * 100));

  return {
    active:true,
    leftSec,
    leftText: humanizeSeconds(leftSec),
    dueLocal: timer.due_at_local || "-",
    setLocal: timer.last_set_at_local || "-",
    pct
  };
}

let lastData = null;

async function refreshStatus() {
  const data = await fetchStatus();
  if(!data) return;

  const wasTzReady = tzReady;
  await ensureTzOnce();

  let finalData = data;
  if (!wasTzReady && tzReady) {
    const data2 = await fetchStatus();
    if (data2) finalData = data2;
  }

  lastData = finalData;

  const r = calc(finalData.timers.rudolph, finalData.server_now, 3*3600);
  const b = calc(finalData.timers.bandage, finalData.server_now, 1*3600);

  renderCtl("rudolph", r.active);
  renderCtl("bandage", b.active);

  document.getElementById('rudolph_left').textContent = r.leftText;
  document.getElementById('bandage_left').textContent = b.leftText;

  document.getElementById('rudolph_line').textContent =
    r.active ? `다음 알림 ${r.dueLocal} (남은 ${r.leftText})` : "설정 없음";

  document.getElementById('bandage_line').textContent =
    b.active ? `다음 알림 ${b.dueLocal} (남은 ${b.leftText})` : "설정 없음";

  document.getElementById('rudolph_bar').style.width = r.pct + "%";
  document.getElementById('bandage_bar').style.width = b.pct + "%";

  if(document.getElementById('modalBg').style.display === 'flex') {
    renderDetail();
  }

  const dm = await fetchDmHealth();
  if(dm && dm.dm_status === 'ok') {
    hideWarn();
  }
}

function renderDetail() {
  const data = lastData;
  if(!data) return;

  const r = calc(data.timers.rudolph, data.server_now, 3*3600);
  const b = calc(data.timers.bandage, data.server_now, 1*3600);

  const rows = [
    { type:"rudolph", name: "루돌프 코 (3시간)", due: r.dueLocal, left: r.leftText, set: r.setLocal, pct: r.pct, active: r.active},
    { type:"bandage", name: "반창고 (1시간)", due: b.dueLocal, left: b.leftText, set: b.setLocal, pct: b.pct, active: b.active}
  ];

  document.getElementById('detailBody').innerHTML = rows.map(x => `
    <tr>
      <td>${x.name}</td>
      <td>${x.due}</td>
      <td>${x.left}</td>
      <td>${x.set}</td>
      <td>${Math.round(x.pct)}%</td>
    </tr>
  `).join('');
}

async function openDetail() {
  document.getElementById('modalBg').style.display = 'flex';
  await refreshStatus();
  renderDetail();
}

function closeDetail(e) {
  if (e && e.target && e.target.id !== 'modalBg') return;
  document.getElementById('modalBg').style.display = 'none';
}

// 초기 실행
refreshStatus();
setInterval(refreshStatus, 30000);
