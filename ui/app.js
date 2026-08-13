/* ─── TOAST NOTIFICATION SYSTEM ─────────────────────────────────────────── */
function showToast(title, message) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = 'toast-message';
    toast.innerHTML = `<div class="toast-title">${escapeHtml(title)}</div><div class="toast-body">${escapeHtml(message)}</div>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

/* ═══════════════════════════════════════════════════════════════════════════
   ORANİX PRO v10000.0 — QUANTUM SINGULARITY GOD ULTRA FRONTEND ENGINE
   ═══════════════════════════════════════════════════════════════════════════ */

let allMatches          = [];
let allAnalyses         = {};
let currentView         = 'matches';
let selectedLeague      = 'all';
let myCouponSlip        = [];
let soundEnabled        = true;
let activeModalTab      = 'tab1';
let currentModalMatchId = null;

let refreshCountdown    = 10;
let refreshTimerId      = null;
let matchesRequestActive = false;
let analysisRequestActive = false;
let lastLoadMeta         = {};
let lastSystemHealth     = {};
let analysisFailedIds    = new Set();
let slipRiskRequestSeq   = 0;

let previousScores      = {};
let updateCheckTimer    = null;

function isLiveMatch(m) {
    const status = String(m?.status || '').toUpperCase();
    return status.includes('PROGRESS') || status.includes('HALFTIME') || status.includes('IN_PLAY') || status === 'LIVE';
}

function isFinishedMatch(m) {
    const status = String(m?.status || '').toUpperCase();
    return ['POST', 'FINISHED', 'FULL_TIME', 'FULL-TIME', 'FT', 'ENDED', 'COMPLETE', 'COMPLETED', 'AFTER_EXTRA_TIME', 'AFTER_PENALTIES'].includes(status)
        || status.includes('FINISHED') || status.includes('FULL_TIME');
}

function scoreBoardHtml(m, size = 20) {
    if (!m?.live_score) return '';
    const home = Number(m.live_score.home);
    const away = Number(m.live_score.away);
    if (!Number.isFinite(home) || !Number.isFinite(away)) return '';
    return `<div class="score-board" aria-label="${escapeHtml(m.home.name)} ${home}, ${escapeHtml(m.away.name)} ${away}" style="font-size:${size}px">
        <span class="score-side score-side-home" title="Ev sahibi: ${escapeHtml(m.home.name)}"><small>EV</small>${home}</span>
        <span class="score-separator">–</span>
        <span class="score-side score-side-away" title="Deplasman: ${escapeHtml(m.away.name)}"><small>DEP</small>${away}</span>
    </div>`;
}

/* ─── MOBILE QR MODAL ────────────────────────────────────────────────────── */
async function openQrModal() {
    playSound('click');
    const modal = document.getElementById('qrModalOverlay');
    if (modal) modal.classList.add('open');

    const qrContainer = document.getElementById('qrCodeImageContainer');
    const qrUrlText   = document.getElementById('qrUrlText');

    if (qrContainer) {
        qrContainer.innerHTML = '<div class="loading-spinner"></div><p style="font-size:11px;color:var(--text-3);margin-top:8px">Wi-Fi IP & QR Kod oluşturuluyor...</p>';
    }

    const info = await callApi('get_local_qr_info');
    if (info) {
        if (qrContainer) {
            qrContainer.innerHTML = `
                <img src="${info.qr_image_url}" alt="Mobil QR" style="width:220px;height:220px;border-radius:12px;display:block;margin:0 auto;box-shadow:0 0 16px rgba(16,185,129,0.3)"
                     onerror="this.outerHTML='<div style=\\'color:red;font-size:12px\\'>QR kod yüklenemedi. İnternet bağlantınızı kontrol edin.</div>'">
            `;
        }
        if (qrUrlText) {
            qrUrlText.innerHTML = `🌐 Mobil Web Bağlantısı: <a href="${info.url}" target="_blank" style="color:var(--green-lt);font-weight:800">${info.url}</a>`;
        }
    }
}

function closeQrModal() {
    playSound('click');
    const modal = document.getElementById('qrModalOverlay');
    if (modal) modal.classList.remove('open');
}

/* ─── WHATSAPP SHARE ─────────────────────────────────────────────────────── */
async function shareWhatsappCoupon() {
    if (!myCouponSlip.length) return;
    playSound('click');
    const text = await callApi('export_coupon_text', myCouponSlip.map(b => ({
        match: b.matchName, bet_label: b.betLabel, odds: b.odds, prob: b.prob
    })));

    if (text) {
        const encoded = encodeURIComponent(text);
        window.open(`https://api.whatsapp.com/send?text=${encoded}`, '_blank');
    }
}

/* ─── SPEECH RECOGNITION (VOICE INPUT ENGINE) ───────────────────────────── */
function startVoiceRecognition() {
    playSound('click');
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        alert('Tarayıcınız veya pywebview ses tanıma desteği sunmuyor. Lütfen yazarak soru sorun.');
        return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'tr-TR';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    const chatWin = document.getElementById('aiChatWindow');
    if (chatWin && !chatWin.classList.contains('open')) chatWin.classList.add('open');

    const msgContainer = document.getElementById('aiChatMessages');
    msgContainer.innerHTML += `<div class="ai-msg bot">🎙️ Sesiniz dinleniyor... Lütfen konuşun!</div>`;
    msgContainer.scrollTop = msgContainer.scrollHeight;

    recognition.start();

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        const inputEl = document.getElementById('aiChatInput');
        if (inputEl) {
            inputEl.value = transcript;
            sendChatMessage();
        }
    };

    recognition.onerror = (event) => {
        msgContainer.innerHTML += `<div class="ai-msg bot" style="color:var(--red)">🎙️ Ses anlaşılamadı. Lütfen tekrar deneyin.</div>`;
    };
}

/* ─── CSV REPORT EXPORTER ────────────────────────────────────────────────── */
async function exportCsvReport() {
    playSound('click');
    const msg = await callApi('export_csv_report');
    if (msg) alert(msg);
}

/* ─── TELEGRAM SHARE ─────────────────────────────────────────────────────── */
async function shareTelegramCoupon() {
    if (!myCouponSlip.length) return;
    playSound('click');
    const text = await callApi('export_coupon_text', myCouponSlip.map(b => ({
        match: b.matchName, bet_label: b.betLabel, odds: b.odds, prob: b.prob
    })));

    if (text) {
        const encoded = encodeURIComponent(text);
        window.open(`https://t.me/share/url?url=${encoded}`, '_blank');
    }
}

/* ─── AI VOICE SYNTHESIS ─────────────────────────────────────────────────── */
function speakPrediction(text) {
    if (!('speechSynthesis' in window)) return;
    try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'tr-TR';
        utterance.rate = 1.0;
        window.speechSynthesis.speak(utterance);
    } catch(e) {}
}

/* ─── AUTO-REFRESH TIMER ─────────────────────────────────────────────────── */
function startAutoRefreshTimer() {
    if (refreshTimerId) clearInterval(refreshTimerId);
    refreshTimerId = setInterval(() => {
        refreshCountdown--;
        const timerEl = document.getElementById('refreshTimer');
        if (timerEl) timerEl.textContent = refreshCountdown;

        if (refreshCountdown <= 0) {
            refreshCountdown = 10;
            loadMatches(true);
        }
    }, 1000);
}

/* ─── AI CHATBOT SYSTEM ──────────────────────────────────────────────────── */
function toggleChatbot() {
    playSound('click');
    const win = document.getElementById('aiChatWindow');
    win.classList.toggle('open');
}

function sendQuickChip(text) {
    const inputEl = document.getElementById('aiChatInput');
    if (inputEl) {
        inputEl.value = text;
        sendChatMessage();
    }
}

async function sendChatMessage() {
    const inputEl = document.getElementById('aiChatInput');
    const msgContainer = document.getElementById('aiChatMessages');
    const query = (inputEl.value || '').trim();
    if (!query) return;

    playSound('click');
    msgContainer.innerHTML += `<div class="ai-msg user">${escapeHtml(query)}</div>`;
    inputEl.value = '';
    msgContainer.scrollTop = msgContainer.scrollHeight;

    const botLoadingId = 'bot_msg_' + Date.now();
    msgContainer.innerHTML += `<div class="ai-msg bot" id="${botLoadingId}">🤖 Deep Learning Neural Network analiz ediliyor...</div>`;
    msgContainer.scrollTop = msgContainer.scrollHeight;

    const response = await callApi('ask_ai_bot', query);
    const botMsgEl = document.getElementById(botLoadingId);

    if (botMsgEl) {
        botMsgEl.innerHTML = response || "🤖 Üzgünüm, şu an canlı yanıt alınamadı.";
    }
    msgContainer.scrollTop = msgContainer.scrollHeight;
}

function escapeHtml(text) {
    return String(text ?? '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ─── WEB AUDIO API SOUND SYSTEM ────────────────────────────────────────── */
let audioCtx = null;

function playSound(type) {
    if (!soundEnabled) return;
    try {
        if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (audioCtx.state === 'suspended') audioCtx.resume();

        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);

        const now = audioCtx.currentTime;

        if (type === 'click') {
            osc.frequency.setValueAtTime(440, now);
            osc.frequency.exponentialRampToValueAtTime(880, now + 0.05);
            gain.gain.setValueAtTime(0.08, now);
            gain.gain.linearRampToValueAtTime(0, now + 0.05);
            osc.start(now); osc.stop(now + 0.05);
        } else if (type === 'add_bet') {
            osc.type = 'triangle';
            osc.frequency.setValueAtTime(523.25, now);
            osc.frequency.exponentialRampToValueAtTime(783.99, now + 0.15);
            gain.gain.setValueAtTime(0.12, now);
            gain.gain.linearRampToValueAtTime(0, now + 0.15);
            osc.start(now); osc.stop(now + 0.15);
        } else if (type === 'remove_bet') {
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(400, now);
            osc.frequency.exponentialRampToValueAtTime(200, now + 0.08);
            gain.gain.setValueAtTime(0.08, now);
            gain.gain.linearRampToValueAtTime(0, now + 0.08);
            osc.start(now); osc.stop(now + 0.08);
        } else if (type === 'goal') {
            osc.type = 'sine';
            osc.frequency.setValueAtTime(1046.50, now);
            osc.frequency.exponentialRampToValueAtTime(1318.51, now + 0.1);
            osc.frequency.exponentialRampToValueAtTime(1567.98, now + 0.25);
            gain.gain.setValueAtTime(0.25, now);
            gain.gain.linearRampToValueAtTime(0, now + 0.3);
            osc.start(now); osc.stop(now + 0.3);
        }
    } catch(e) {}
}

function toggleSound() {
    soundEnabled = !soundEnabled;
    document.getElementById('soundIcon').textContent = soundEnabled ? '🔊' : '🔇';
    document.getElementById('soundLabel').textContent = soundEnabled ? 'Ses Efektleri Açık' : 'Ses Efektleri Kapalı';
}

function changeTheme(theme) {
    playSound('click');
    document.body.className = `theme-${theme}`;
    localStorage.setItem('oranix-theme', theme);
}

/* ─── DYNAMIC PARTICLES CANVAS BACKGROUND ────────────────────────────────── */
function initBackgroundCanvas() {
    const canvas = document.getElementById('bgCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let width = canvas.width = window.innerWidth;
    let height = canvas.height = window.innerHeight;

    window.addEventListener('resize', () => {
        width = canvas.width = window.innerWidth;
        height = canvas.height = window.innerHeight;
    });

    const particles = Array.from({ length: 50 }, () => ({
        x: Math.random() * width, y: Math.random() * height,
        r: Math.random() * 2 + 1, vx: (Math.random() - 0.5) * 0.4, vy: (Math.random() - 0.5) * 0.4,
        alpha: Math.random() * 0.5 + 0.1
    }));

    function draw() {
        ctx.clearRect(0, 0, width, height);
        particles.forEach(p => {
            p.x += p.vx; p.y += p.vy;
            if (p.x < 0) p.x = width; if (p.x > width) p.x = 0;
            if (p.y < 0) p.y = height; if (p.y > height) p.y = 0;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(99, 102, 241, ${p.alpha})`;
            ctx.fill();
        });

        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 130) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(99, 102, 241, ${0.08 * (1 - dist / 130)})`;
                    ctx.lineWidth = 0.6;
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(draw);
    }
    draw();
}

/* ─── UNBREAKABLE LOGO RENDERER ───────────────────────────────────────────── */
function renderTeamLogoHtml(team, size=44) {
    const color    = team.color || '#6366f1';
    const alt      = team.alt_color || '#ffffff';
    const short    = (team.short_name || team.name || '?').slice(0, 3).toUpperCase();
    const primary  = team.logo || '';
    const fallback = team.logo_fallback || '';

    const shieldBadgeHtml = `
        <div class="team-crest-badge" style="width:${size}px;height:${size}px;background:radial-gradient(circle, ${color} 0%, #000 120%);color:${alt}">
            ${short}
        </div>`;

    if (!primary && !fallback) {
        return shieldBadgeHtml;
    }

    return `
        <img class="team-logo" src="${primary}" alt="${team.name}" style="width:${size}px;height:${size}px"
             onerror="if('${fallback}' && this.src !== '${fallback}'){ this.src='${fallback}'; } else { this.style.display='none'; this.nextElementSibling.style.display='flex'; }">
        <div class="team-crest-badge" style="width:${size}px;height:${size}px;background:radial-gradient(circle, ${color} 0%, #000 120%);color:${alt};display:none">
            ${short}
        </div>`;
}

/* ─── MACKOLIK LIVE SCOREBOARD SLIDER ──────────────────────────────────────── */
function buildMackolikLiveBar() {
    const slider = document.getElementById('mackolikLiveSlider');
    if (!slider) return;

    const liveMatches = allMatches.filter(m => m.status && (m.status.includes('PROGRESS') || m.status.includes('HALFTIME')));
    if (!liveMatches.length) {
        slider.innerHTML = '<div class="mlb-item">Şu an oynanan canlı maç bulunmuyor. Yaklaşan maçlar aşağıda listelenmiştir.</div>';
        return;
    }

    slider.innerHTML = liveMatches.map(m => {
        const sc = m.live_score ? `${m.live_score.home} - ${m.live_score.away}` : '0 - 0';
        return `
        <div class="mlb-item" onclick…27905 tokens truncated…>${x.match}</div>
                            <div style="font-size:11px;color:var(--text-3);margin-top:2px">${x.league || ''} ${x.date ? '• ' + x.date : ''} ${x.time ? '• ' + x.time : ''}</div>
                        </div>
                    </div>
                    <div style="text-align:right;flex-shrink:0">
                        <div style="font-size:18px;font-weight:900;font-family:'JetBrains Mono';color:var(--green-lt)">${x.xg_total?.toFixed(2) || '–'} xG</div>
                        <div style="font-size:10px;color:var(--text-3)">${x.xg_home || '–'} – ${x.xg_away || '–'}</div>
                    </div>
                </div>
            `).join('');
        }
    }
}

/* ─── DROPPING ODDS PAGE ─────────────────────────────────────────────────────── */
async function renderDroppingOdds() {
    const container = document.getElementById('droppingList');
    container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Oran düşüşleri analiz ediliyor...</p></div>';

    const items = await callApi('get_dropping_odds');
    if (!items || !items.length) {
        container.innerHTML = '<div class="empty-state"><h3>Belirgin oran düşüşü tespit edilmedi</h3></div>';
        return;
    }

    container.innerHTML = items.map(it => `
        <div class="match-card" style="margin-bottom:12px" onclick="openModal('${it.match.id}')">
            <div class="card-league" style="background:rgba(239,68,68,0.1)">
                <span style="color:var(--red);font-weight:800">🔥 %${Math.abs(it.drop_pct)} ORAN DÜŞÜŞÜ (HOT MONEY)</span>
                <span>${it.match.match_time}</span>
            </div>
            <div class="card-teams">
                <div class="card-team"><div class="team-name">${it.match.home.name}</div></div>
                <div style="font-weight:800;color:var(--purple-lt)">VS</div>
                <div class="card-team"><div class="team-name">${it.match.away.name}</div></div>
            </div>
            <div style="padding:10px 14px;font-size:12px;color:var(--text-2);text-align:center">
                Açılış Oranı: <strong style="text-decoration:line-through">${it.match.odds_open}</strong> → Güncel: <strong style="color:var(--green-lt)">${it.match.home_odds}</strong>
            </div>
        </div>`).join('');
}

/* ─── VALUE BETS PAGE ─────────────────────────────────────────────────────────── */
function renderValueBets() {
    const container = document.getElementById('valueList');
    const valueBets = [];

    allMatches.forEach(m => {
        const a = allAnalyses[m.id];
        if (!a || !a.all_ev) return;
        ['home', 'draw', 'away'].forEach(k => {
            const ev = a.all_ev[k];
            if (ev && ev.is_value) {
                valueBets.push({
                    matchId: m.id, match: `${m.home.name} vs ${m.away.name}`,
                    league: m.league, time: m.match_time, bet: ev.label,
                    odds: ev.odds, prob: ev.prob, ev: ev.ev, kelly: ev.kelly_pct
                });
            }
        });
    });

    valueBets.sort((a,b) => b.ev - a.ev);

    if (!valueBets.length) {
        container.innerHTML = '<div class="empty-state"><h3>Şu an +EV bahis bulunamadı</h3></div>';
        return;
    }

    container.innerHTML = valueBets.map(v => `
        <div class="match-card" style="margin-bottom:10px;padding:16px" onclick="openModal('${v.matchId}')">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                    <div style="font-size:14px;font-weight:700">${v.match}</div>
                    <div style="font-size:11px;color:var(--text-3);margin-top:2px">${v.league} • ${v.time}</div>
                    <div style="font-size:13px;font-weight:800;color:var(--green-lt);margin-top:6px">💎 Tahmin: ${v.bet} (%${v.prob})</div>
                </div>
                <div style="text-align:right">
                    <div style="font-size:18px;font-weight:900;color:var(--green-lt)">+${v.ev}% EV</div>
                    <div style="font-size:14px;font-weight:800;color:var(--amber)">@ ${v.odds}</div>
                    <div style="font-size:10px;color:var(--text-3)">Kasa: %${v.kelly}</div>
                </div>
            </div>
        </div>`).join('');
}

/* ─── SAVED COUPONS ─────────────────────────────────────────────────────────── */
async function loadSavedCoupons() {
    const container = document.getElementById('savedList');
    const coupons = await callApi('get_saved_coupons');

    if (!coupons || !coupons.length) {
        container.innerHTML = '<div class="empty-state"><h3>Henüz kayıtlı kuponunuz yok</h3></div>';
        return;
    }

    container.innerHTML = coupons.map((c, i) => {
        const picks = Array.isArray(c) ? c : (c.picks || []);
        return `
        <div class="saved-coupon-card">
            <div class="saved-coupon-head">
                <div><strong>${escapeHtml(c.coupon_id || `Kupon #${i+1}`)}</strong><span>${picks.length} maç · @${Number(c.total_odds || 1).toFixed(2)}</span></div>
                <div class="saved-coupon-actions">
                    <select aria-label="Kupon durumu" onchange="updateSavedCouponStatus('${escapeHtml(c.coupon_id)}', this.value)">
                        ${['BEKLEYEN','KAZANDI','KAYBETTİ','İPTAL'].map(s => `<option ${c.status===s?'selected':''}>${s}</option>`).join('')}
                    </select>
                    <button onclick="deleteSavedCoupon('${escapeHtml(c.coupon_id)}')" title="Kuponu sil">Sil</button>
                </div>
            </div>
            ${picks.map(b => `<div style="font-size:12px;color:var(--text-2);margin-bottom:2px">• ${b.matchName || b.match} — ${b.betLabel || b.tip || 'Tahmin'} (@${b.odds})</div>`).join('')}
        </div>`;
    }).join('');
}

async function renderModelPerformance() {
    const container = document.getElementById('modelPerformanceContent');
    if (!container) return;
    container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Gerçek performans kayıtları hazırlanıyor…</p></div>';
    const data = await callApi('get_model_performance');
    if (!data) {
        container.innerHTML = '<div class="performance-empty">Model karnesi şu an okunamadı.</div>';
        return;
    }
    const learning = data.learning || {};
    const laboratory = data.laboratory || {};
    const gate = data.model_gate || {};
    const settled = Number(learning.settled_predictions || 0);
    const ready = settled >= 30;
    const metric = (value, suffix = '') => value == null ? '—' : `${value}${suffix}`;
    const leagueRows = (learning.league_backtest || []).map(item => `
        <div class="league-proof-row">
            <div><strong>${item.league}</strong><small>${item.samples} sonuç · Lig sıcaklığı T=${item.temperature ?? 1}</small></div>
            <span class="proof-grade grade-${item.grade || 'C'}">${item.grade || 'C'}</span>
            <div class="proof-brier"><small>Brier</small><b>${item.brier}</b></div>
        </div>`).join('') || '<div class="performance-empty compact">Lig kanıtı için sonuçlar birikiyor.</div>';
    const reliability = (learning.reliability_bins || []).map(bin => `
        <div class="reliability-row"><span>%${bin.range}</span><div><i style="width:${Math.min(100, bin.confidence_pct)}%"></i><em style="width:${Math.min(100, bin.accuracy_pct)}%"></em></div><b>%${bin.accuracy_pct}</b><small>${bin.samples} maç</small></div>`).join('') || '<div class="performance-empty compact">Kalibrasyon grafiği 30 sonuçtan sonra açılır.</div>';
    const modelRows = (gate.models || []).map(model => `
        <div class="model-gate-row"><div><strong>${model.version}</strong><small>${model.samples} sonuç</small></div><span>Brier <b>${model.brier}</b></span><span>Doğruluk <b>%${model.accuracy_pct}</b></span></div>`).join('') || '<div class="performance-empty compact">Aday model karşılaştırması için sonuç bekleniyor.</div>';
    container.innerHTML = `
        <div class="performance-score-grid">
            <div class="performance-score-card primary"><span>KİLİTLİ VE SONUÇLANMIŞ</span><strong>${settled}</strong><small>${learning.pending_settlements || 0} sonuç bekliyor</small></div>
            <div class="performance-score-card"><span>BRIER SKORU</span><strong>${metric(learning.brier_score)}</strong><small>Düşük değer daha iyidir</small></div>
            <div class="performance-score-card"><span>1X2 DOĞRULUK</span><strong>${metric(learning.accuracy_pct, '%')}</strong><small>${ready ? 'Gerçek maç sonucu' : 'Henüz doğrulanmadı'}</small></div>
            <div class="performance-score-card"><span>KALİBRASYON HATASI</span><strong>${metric(learning.ece_pct, '%')}</strong><small>${learning.calibration_status || 'Veri bekleniyor'}</small></div>
        </div>
        <div class="performance-truth-banner ${ready ? 'is-ready' : ''}">
            <div><span>${ready ? '✓' : '…'}</span><strong>${ready ? 'Gerçek kalibrasyon aktif' : 'Kanıt birikiyor'}</strong><small>${learning.drift_status || 'Model izleniyor'} · ${learning.locked_predictions || 0} maç öncesi tahmin kilitlendi</small></div>
            <div><b>${laboratory.historical_matches || 0}</b><small>geçmiş maç</small></div>
            <div><b>${laboratory.leagues || 0}</b><small>izlenen lig</small></div>
        </div>
        <div class="performance-columns">
            <section class="performance-panel"><header><div><span>LİG BAZLI KANIT</span><strong>Walk-forward ve canlı sonuçlar</strong></div></header><div class="league-proof-list">${leagueRows}</div></section>
            <section class="performance-panel"><header><div><span>KALİBRASYON</span><strong>Söylenen güven / gerçekleşen başarı</strong></div><small>Mor: güven · Yeşil: başarı</small></header><div class="reliability-list">${reliability}</div></section>
        </div>
        <section class="performance-panel model-gate-panel"><header><div><span>GÜVENLİ MODEL KAPISI</span><strong>Yeni motor eski motoru kanıtsız değiştiremez</strong></div><small>${gate.status || 'Veri bekleniyor'} · En az ${gate.minimum_samples || 100} sonuç</small></header><div>${modelRows}</div></section>`;
}

async function deleteSavedCoupon(couponId) {
    const ok = await callApi('delete_coupon', couponId);
    showToast(ok ? 'Kupon silindi' : 'İşlem tamamlanamadı', ok ? couponId : 'Kupon bulunamadı');
    loadSavedCoupons();
}

async function updateSavedCouponStatus(couponId, status) {
    const ok = await callApi('update_coupon_status', couponId, status);
    showToast(ok ? 'Durum güncellendi' : 'Güncelleme başarısız', `${couponId}: ${status}`);
}

/* ─── ELO & POWER RANKINGS MATRIX VIEW ──────────────────────────────────── */
async function renderPowerRankings() {
    const container = document.getElementById('powerRankingsContent');
    if (!container) return;

    container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>ELO ve Takım Güç Sıralaması matrisi hesaplanıyor...</p></div>';

    const rankings = await callApi('get_power_rankings');
    if (!rankings || !rankings.length) {
        container.innerHTML = '<div class="empty-state"><h3>Güç sıralaması alınamadı</h3></div>';
        return;
    }

    container.innerHTML = `
        <div style="background:var(--bg-card);padding:18px;border-radius:14px;border:1px solid var(--border-lt);overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;font-size:12px">
                <thead>
                    <tr style="border-bottom:1px solid var(--border-lt);text-align:left;color:var(--text-3);font-size:11px">
                        <th style="padding:8px">MAÇ</th>
                        <th style="padding:8px">LİG</th>
                        <th style="padding:8px">EV ELO / GÜÇ</th>
                        <th style="padding:8px">DEP ELO / GÜÇ</th>
                        <th style="padding:8px">GÜÇ FARKI</th>
                        <th style="padding:8px">MOMENTUM</th>
                    </tr>
                </thead>
                <tbody>
                    ${rankings.map(r => `
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
                            <td style="padding:10px;font-weight:800">${r.match}</td>
                            <td style="padding:10px;color:var(--text-3)">${r.league} • ${r.time}</td>
                            <td style="padding:10px;color:var(--purple-lt)">${r.elo_home.toFixed(0)} (${r.power_home} pts)</td>
                            <td style="padding:10px;color:var(--cyan)">${r.elo_away.toFixed(0)} (${r.power_away} pts)</td>
                            <td style="padding:10px;font-weight:900;color:${r.power_diff>=0?'var(--green-lt)':'var(--red)'}">${r.power_diff>=0?'+':''}${r.power_diff}</td>
                            <td style="padding:10px;font-size:11px">Ev %${r.momentum_home} | Dep %${r.momentum_away}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}


/* ─── MANUAL REFRESH BUTTON HANDLER ────────────────────────────────────────── */
function manualRefresh() {
    playSound('click');
    loadMatches(false);
}


/* ─── MACKOLIK CANLI SKOR BANDI UPDATER ───────────────────────────────────── */
async function updateMackolikLiveBar() {
    const slider = document.getElementById('mackolikLiveSlider');
    if (!slider) return;
    if (!allMatches.length) {
        slider.innerHTML = '<div class="mlb-item">Maçlar yükleniyor...</div>';
        return;
    }
    const live = allMatches.filter(m => m.live_score || m.status === 'live');
    if (!live.length) {
        slider.innerHTML = '<div class="mlb-item" style="color:var(--text-3)">Şu an canlı maç yok</div>';
        return;
    }
    slider.innerHTML = live.map(m => {
        const sc = m.live_score ? `${m.live_score.home}-${m.live_score.away}` : '? - ?';
        const min = m.minute ? `<span class="mlb-clock">${m.minute}'</span>` : '';
        return `<div class="mlb-item" onclick="openModal('${m.id}')">
            ${min}
            <span class="mlb-team">${m.home.name}</span>
            <span class="mlb-score">${sc}</span>
            <span class="mlb-team">${m.away.name}</span>
        </div>`;
    }).join('');
}
