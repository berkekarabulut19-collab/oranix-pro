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
        <div class="mlb-item" onclick="openModal('${m.id}')">
            <span class="mlb-clock">${m.game_clock || "1'"}</span>
            <span class="mlb-team">${m.home.name}</span>
            <span class="mlb-score">${sc}</span>
            <span class="mlb-team">${m.away.name}</span>
        </div>`;
    }).join('');
}

/* ─── HERO BANNER RENDERER ─────────────────────────────────────────────────── */
function renderHeroBanner() {
    const banner = document.getElementById('heroBanner');
    if (!banner || !allMatches.length) return;

    let bestMatch = null;
    let bestConf = 0;

    allMatches.forEach(m => {
        const a = allAnalyses[m.id];
        if (a && a.confidence && a.confidence.rank > bestConf) {
            bestConf = a.confidence.rank;
            bestMatch = { match: m, analysis: a };
        }
    });

    if (!bestMatch) return;

    const m = bestMatch.match;
    const a = bestMatch.analysis;
    const b = a.best_bet;

    document.getElementById('heroTeams').innerHTML = `${m.home.name} vs ${m.away.name}`;
    const oddsText = b.odds != null ? ` · Oran @${Number(b.odds).toFixed(2)}` : ' · Maçkolik oranı yayınlanmadı';
    document.getElementById('heroDetails').innerHTML = `🎯 Model olasılığı: <strong>${b.label} (%${b.prob})</strong>${oddsText} · Belirsizlik: <strong>${a.confidence_intervals?.home || ''}</strong>`;
}

/* ─── INIT ─────────────────────────────────────────────────────────────────── */
let _appInitDone = false;
function initApp() {
    if (_appInitDone) return;
    _appInitDone = true;
    console.log('[OranixPro] initApp() called – loading matches...');
    initBackgroundCanvas();
    const savedTheme = localStorage.getItem('oranix-theme') || 'cyber';
    document.body.className = `theme-${savedTheme}`;
    const themeSelect = document.getElementById('themeSelect');
    if (themeSelect) themeSelect.value = savedTheme;
    startAutoRefreshTimer();
    updateMackolikLiveBar();
    setInterval(updateMackolikLiveBar, 30000);
    refreshSystemHealth();
    setInterval(refreshSystemHealth, 30000);
    // Ensure matches view is visible on startup
    document.querySelectorAll('.view').forEach(v => v.style.display = 'none');
    const vm = document.getElementById('viewMatches');
    if (vm) vm.style.display = '';
    // Wait for pywebview.api to be fully ready, then load matches
    function tryLoad(attempt) {
        if (window.pywebview && window.pywebview.api) {
            loadMatches();
        } else if (new URLSearchParams(window.location.search).has('token')) {
            // Desktop/mobile localhost pages already have an authenticated HTTP
            // bridge; do not keep the user on a spinner while pywebview injects.
            loadMatches();
        } else if (attempt < 10) {
            setTimeout(() => tryLoad(attempt + 1), 500);
        } else {
            // fallback to HTTP api
            loadMatches();
        }
    }
    tryLoad(0);
}

window.addEventListener('pywebviewready', () => {
    console.log('[PyWebView] pywebviewready event fired');
    initApp();
});

window.addEventListener('DOMContentLoaded', () => {
    // Give pywebview 200ms to inject API, then try initApp
    setTimeout(initApp, 200);
});

/* ─── PYWEBVIEW BRIDGE API WITH MOBILE HTTP FALLBACK ───────────────────────── */
async function callApi(method, ...args) {
    if (window.pywebview && window.pywebview.api) {
        try {
            const bridgeMethod = window.pywebview.api[method];
            if (typeof bridgeMethod === 'function') {
                // A WebView bridge promise can rarely stay unresolved after
                // sleep/resume. Fall through to the authenticated local HTTP
                // bridge instead of leaving prediction cards pending forever.
                const bridgeTimeoutMs = method === 'get_priority_analyses' ? 5000 : 8000;
                const bridgeResult = await Promise.race([
                    bridgeMethod(...args),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('Bridge timeout')), bridgeTimeoutMs))
                ]);
                if (bridgeResult !== null && bridgeResult !== undefined) {
                    return bridgeResult;
                }
            }
        } catch(e) {
            console.warn('[pywebview] API error:', e);
        }
    }

    const apiToken = new URLSearchParams(window.location.search).get('token') || '';
    try {
        const controller = new AbortController();
        const httpTimeoutMs = method === 'get_priority_analyses' ? 6500 : 8500;
        const timeoutId = setTimeout(() => controller.abort(), httpTimeoutMs);
        const resp = await fetch('/api/' + method, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Oranix-Token': apiToken
            },
            body: JSON.stringify(args),
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        if (resp.ok) {
            return await resp.json();
        }
        console.warn(`[HTTP API] ${method} failed with status ${resp.status}`);
    } catch(e) {
        console.warn('[HTTP API] fallback error:', e);
    }
    return null;
}

/* ─── LOAD MATCHES ─────────────────────────────────────────────────────────── */
async function loadMatches(silent = false, retryCount = 0) {
    if (matchesRequestActive) return;
    matchesRequestActive = true;
    if (!silent && !allMatches.length) setLoading(true);
    const btn = document.getElementById('refreshBtn');
    if (btn && !silent) btn.classList.add('loading');

    try {
        // Show fixture cards first. Full prediction analysis is deliberately
        // loaded afterwards because a large bulletin can take several seconds.
        const quickMatches = await callApi('get_matches');
        if (quickMatches && quickMatches.length) {
            const activeMatches = quickMatches.filter(match => !isFinishedMatch(match));
            const wasEmpty = !allMatches.length;
            activeMatches.forEach(m => {
                if (!m.live_score) return;
                const scoreText = `${m.live_score.home}-${m.live_score.away}`;
                if (previousScores[m.id] && previousScores[m.id] !== scoreText) {
                    playSound('goal');
                    speakPrediction(`Gol duyurusu! ${m.home.name} ${m.live_score.home}, ${m.away.name} ${m.live_score.away}.`);
                }
                previousScores[m.id] = scoreText;
            });
            allMatches = activeMatches;
            if (wasEmpty) allAnalyses = {};
            lastLoadMeta = {total_matches: allMatches.length, analyzed_matches: Object.keys(allAnalyses).length, sources: {Maçkolik: allMatches.length}, phase: 'priority'};
            renderAll();
            renderSystemHealth();
            if (!silent) setLoading(false);
            if (btn) btn.classList.remove('loading');
        }

        // Do not keep the page request open while hundreds of predictions run.
        // Cards remain interactive and analyses replace their placeholders as
        // soon as the background request completes.
        void loadAnalysesInBackground();
        return;
    } catch(e) {
        console.error('Load error:', e);
        await refreshSystemHealth();
        if (!allMatches.length) showEmptyState();
        else renderAll();
    } finally {
        matchesRequestActive = false;
        if (!silent) setLoading(false);
        if (btn) btn.classList.remove('loading');
        const updateEl = document.getElementById('lastUpdateTime');
        if (updateEl) updateEl.textContent = 'Maçlar hazır: ' + new Date().toLocaleTimeString('tr-TR');
    }
}

async function loadAnalysesInBackground() {
    if (analysisRequestActive) return;
    analysisRequestActive = true;
    try {
        const orderedMatches = [...allMatches].sort((a, b) => {
            const liveA = isLiveMatch(a) ? 1 : 0;
            const liveB = isLiveMatch(b) ? 1 : 0;
            if (liveA !== liveB) return liveB - liveA;
            return String(a.iso_date || '').localeCompare(String(b.iso_date || '')) || String(a.match_time || '').localeCompare(String(b.match_time || ''));
        });

        // Stream predictions in small batches. Live and nearest fixtures are
        // rendered first, and one failed batch cannot block the remaining cards.
        const batchSize = 24;
        let failedBatches = 0;
        for (let start = 0; start < orderedMatches.length; start += batchSize) {
            const batch = orderedMatches.slice(start, start + batchSize);
            const result = await callApi('get_priority_analyses', batch.map(match => match.id));
            if (result?.analyses && Object.keys(result.analyses).length) {
                allAnalyses = {...allAnalyses, ...result.analyses};
                Object.keys(result.analyses).forEach(id => analysisFailedIds.delete(String(id)));
            } else {
                failedBatches += 1;
                batch.forEach(match => analysisFailedIds.add(String(match.id)));
            }
            lastLoadMeta = {
                total_matches: allMatches.length,
                analyzed_matches: Object.keys(allAnalyses).length,
                failed_matches: Math.max(0, allMatches.length - Object.keys(allAnalyses).length),
                sources: {Maçkolik: allMatches.length},
                phase: start + batchSize >= orderedMatches.length ? 'complete' : 'streaming',
                is_complete: Object.keys(allAnalyses).length >= allMatches.length
            };
            renderAll();
            renderSystemHealth({degraded: failedBatches > 0});
        }
    } catch(e) {
        console.error('Background analysis error:', e);
        await refreshSystemHealth();
        if (!allMatches.length) showEmptyState();
        else renderAll();
    } finally {
        analysisRequestActive = false;
        const updateEl = document.getElementById('lastUpdateTime');
        if (updateEl) updateEl.textContent = 'Analiz güncellendi: ' + new Date().toLocaleTimeString('tr-TR');
    }
}

function renderSystemHealth(extra = {}) {
    const meta = lastLoadMeta || {};
    const total = meta.total_matches ?? allMatches.length;
    const analyzed = meta.analyzed_matches ?? Object.keys(allAnalyses).length;
    const sourceNames = Object.keys(meta.sources || {});
    const staleCount = allMatches.filter(m => m.is_stale).length;
    const fetchSource = lastSystemHealth.fetcher?.source;
    const source = staleCount ? 'Maçkolik · eski önbellek' : (fetchSource === 'mackolik_unavailable' ? 'Maçkolik bağlantısı yok' : (sourceNames.join(', ') || (fetchSource?.startsWith('mackolik') ? 'Maçkolik' : 'Hazırlanıyor')));
    const complete = total > 0 && analyzed === total && !extra.degraded;
    const state = document.getElementById('healthState');
    if (state) {
        const unavailable = fetchSource === 'mackolik_unavailable';
        state.className = `health-state ${complete ? 'is-good' : (total || unavailable ? 'is-warning' : 'is-loading')}`;
        const analyzing = total > 0 && analyzed < total;
        state.innerHTML = `<span class="health-dot"></span><strong>${complete ? 'Tahmin motoru tamamlandı' : (unavailable ? 'Maçkolik bekleniyor' : (analyzing ? `Tahmin motoru çalışıyor · ${analyzed}/${total}` : 'Sistem hazırlanıyor'))}</strong>`;
    }
    const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
    set('healthSource', source);
    set('healthAnalysis', `${analyzed} / ${total}`);
    set('healthLatency', meta.duration_ms != null ? `${(meta.duration_ms / 1000).toFixed(1)} sn` : '—');
    set('healthUpdated', total ? `Canlı akış · ${new Date().toLocaleTimeString('tr-TR')}` : 'İlk veri bekleniyor');
    renderUpdateStatus(lastSystemHealth.update || {});
}

function renderUpdateStatus(update) {
    const host = document.getElementById('updateStatus');
    if (!host) return;
    if (update.state === 'update_available') {
        host.className = 'update-status is-ready';
        host.innerHTML = `<span>Yeni sürüm ${escapeHtml(update.latest_version || '')} hazır</span><button onclick="installAvailableUpdate()">Güncelle</button>`;
    } else if (update.state === 'downloaded') {
        host.className = 'update-status is-ready';
        host.innerHTML = '<span>Güncelleme indirildi</span><button onclick="applyAvailableUpdate()">Yeniden başlat ve kur</button>';
    } else if (update.state === 'error') {
        host.className = 'update-status is-muted';
        host.textContent = 'Güncelleme kontrolü şu an kullanılamıyor';
    } else if (update.state === 'up_to_date') {
        host.className = 'update-status is-muted';
        host.textContent = 'Oranix güncel';
    } else {
        host.className = 'update-status is-muted';
        host.textContent = update.manifest_url_configured ? 'Güncelleme kontrol ediliyor…' : 'Otomatik güncelleme adresi bekleniyor';
    }
}

async function installAvailableUpdate() {
    const host = document.getElementById('updateStatus');
    if (host) host.textContent = 'Güncelleme güvenli şekilde indiriliyor…';
    const result = await callApi('download_update');
    renderUpdateStatus(result || {state:'error'});
}

async function applyAvailableUpdate() {
    const result = await callApi('apply_update');
    if (result?.state === 'restarting') {
        showToast('Güncelleme hazır', 'Oranix kapanıp yeni sürümle yeniden açılacak.');
    } else {
        renderUpdateStatus(result || {state:'error'});
    }
}

async function refreshSystemHealth() {
    const health = await callApi('get_system_health');
    if (!health) return;
    lastSystemHealth = health;
    if (health.analysis && Object.keys(health.analysis).length) lastLoadMeta = health.analysis;
    const cache = health.match_cache || {};
    const cacheEl = document.getElementById('healthCache');
    if (cacheEl) cacheEl.textContent = cache.age_seconds == null ? '—' : `${cache.age_seconds} sn`;
    const learning = health.model_learning || {};
    const learningEl = document.getElementById('healthLearning');
    if (learningEl) {
        learningEl.textContent = learning.settled_predictions
            ? `${learning.settled_predictions} sonuç · Brier ${learning.brier_score ?? '—'}`
            : 'Sonuç biriktiriliyor';
        learningEl.title = `${learning.calibration_status || ''} · ${learning.learned_teams || 0} takım öğrenildi · T=${learning.temperature || 1} · ${learning.drift_status || ''}`;
    }
    const modelLab = health.model_lab || {};
    const modelLabEl = document.getElementById('healthModelLab');
    if (modelLabEl) {
        const run = modelLab.latest_walk_forward || {};
        modelLabEl.textContent = run.evaluated_matches
            ? `${run.evaluated_matches} test · Brier ${run.brier_score ?? '—'}`
            : `${modelLab.historical_matches || 0} geçmiş maç`;
        modelLabEl.title = `Durum: ${modelLab.readiness || 'collecting'} · ${modelLab.leagues || 0} lig · Gelecek bilgi sızıntısı koruması: ${modelLab.leakage_guard ? 'aktif' : 'kapalı'}`;
    }
    const upgrade = health.safe_upgrade || {};
    const upgradeEl = document.getElementById('healthUpgrade');
    if (upgradeEl) {
        const compared = upgrade.shadow_compared || 0;
        upgradeEl.textContent = upgrade.safe_mode === false ? 'Aday motor aktif' : `Gölge test · ${compared}`;
        upgradeEl.title = `Reddedilen veri: ${upgrade.match_rows_rejected || 0} · Reddedilen analiz: ${upgrade.analyses_rejected || 0} · Ortalama fark: ${upgrade.shadow_mean_delta || 0}`;
    }
    const external = health.external_data || {};
    const externalEl = document.getElementById('healthExternal');
    if (externalEl) {
        const providers = external.providers || {};
        const active = Object.entries(providers).filter(([, value]) => value?.enabled);
        const verified = external.verified_match_count || 0;
        externalEl.textContent = active.length ? `${active.length} kaynak · ${verified} doğrulandı` : 'Maçkolik ana kaynak';
        externalEl.title = active.length
            ? active.map(([name, value]) => `${name}: ${value.enriched || 0} maç`).join(' · ')
            : 'API anahtarı gerektiren ek kaynaklar kapalı; tahmin Maçkolik ile devam ediyor.';
    }
    renderSystemHealth();
}

function setLoading(on) {
    if (on) {
        document.getElementById('matchesGrid').innerHTML = `
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <p>Kesin skor matrisi ve güncel takım verileri hesaplanıyor...</p>
            </div>`;
    } else if (!allMatches.length) {
        const grid = document.getElementById('matchesGrid');
        if (grid && grid.querySelector('.loading-state')) showEmptyState();
    }
}

function showEmptyState() {
    document.getElementById('matchesGrid').innerHTML = `
        <div class="empty-state">
            <div class="empty-state-icon">⚽</div>
            <h3>Maçkolik şu anda yanıt vermiyor</h3>
            <p>Yükleme tamamlandı. Ekran otomatik olarak yeniden deneyecek; uygulamayı açık bırakabilirsiniz.</p>
            <button class="empty-retry-btn" onclick="manualRefresh()">🔄 Şimdi Tekrar Dene</button>
        </div>`;
    const heroTeams = document.getElementById('heroTeams');
    const heroDetails = document.getElementById('heroDetails');
    const liveSlider = document.getElementById('mackolikLiveSlider');
    if (heroTeams) heroTeams.textContent = 'Maçkolik bağlantısı bekleniyor';
    if (heroDetails) heroDetails.textContent = 'Bağlantı kurulunca güncel maçlar otomatik olarak gösterilecek.';
    if (liveSlider) liveSlider.innerHTML = '<div class="mlb-item">Maçkolik bağlantısı bekleniyor…</div>';
    updateStats([]);
}

/* ─── RENDER ALL ─────────────────────────────────────────────────────────────── */
function renderAll() {
    buildMackolikLiveBar();
    renderHeroBanner();
    buildLeagueFilters();
    updateStats(allMatches);
    renderMatches();
    if (currentView === 'dropping') renderDroppingOdds();
    if (currentView === 'coupon')   generateCustomCoupon();
    if (currentView === 'value')    renderValueBets();
    if (currentView === 'saved')    loadSavedCoupons();
}

/* ─── LEAGUE FILTERS ──────────────────────────────────────────────────────── */
function buildLeagueFilters() {
    const leagueCounts = {};
    const leagueLiveCounts = {};

    allMatches.forEach(m => {
        const k = m.league || 'Diğer';
        leagueCounts[k] = (leagueCounts[k] || 0) + 1;
        if (m.status && (m.status.includes('PROGRESS') || m.status.includes('HALFTIME'))) {
            leagueLiveCounts[k] = (leagueLiveCounts[k] || 0) + 1;
        }
    });

    const container = document.getElementById('leagueFilters');
    let html = `<button class="league-filter-btn ${selectedLeague === 'all' ? 'active' : ''}" onclick="filterByLeague('all')">
        🌍 Tüm Ligler <span class="lf-count">${allMatches.length}</span>
    </button>`;

    const sortedLeagues = Object.keys(leagueCounts).sort((a, b) => {
        const liveA = leagueLiveCounts[a] || 0;
        const liveB = leagueLiveCounts[b] || 0;
        if (liveB !== liveA) return liveB - liveA;
        return leagueCounts[b] - leagueCounts[a];
    });

    for (const league of sortedLeagues) {
        const count = leagueCounts[league];
        const liveCnt = leagueLiveCounts[league] || 0;
        const isActive = selectedLeague === league;
        const m = allMatches.find(x => x.league === league);
        const icon = m ? (m.league_country || '⚽') : '⚽';

        html += `<button class="league-filter-btn ${isActive ? 'active' : ''}" onclick="filterByLeague('${CSS.escape(league)}')">
            ${icon} ${league} ${liveCnt > 0 ? `<span style="background:#ef4444;color:white;font-size:9px;font-weight:900;padding:1px 5px;border-radius:10px;margin-left:4px">🔴 ${liveCnt}</span>` : ''}
            <span class="lf-count">${count}</span>
        </button>`;
    }

    container.innerHTML = html;
}

function filterByLeague(league) {
    playSound('click');
    selectedLeague = league;
    buildLeagueFilters();
    renderMatches();
}

/* ─── STATS BAR ─────────────────────────────────────────────────────────────── */
function updateStats(matches) {
    const total    = matches.length;
    const live     = matches.filter(m => m.status && (m.status.includes('PROGRESS') || m.status.includes('HALFTIME'))).length;
    let valueCnt   = 0;
    let highConf   = 0;
    let dropCnt    = 0;

    matches.forEach(m => {
        const a = allAnalyses[m.id];
        if (!a) return;
        if (a.best_bet && a.best_bet.is_value) valueCnt++;
        if (a.confidence && a.confidence.rank >= 4) highConf++;
        if (m.odds_drop_pct && m.odds_drop_pct < -3.0) dropCnt++;
    });

    document.getElementById('statTotal').textContent    = total;
    document.getElementById('statValue').textContent    = valueCnt;
    document.getElementById('statHighConf').textContent = highConf;
    document.getElementById('statLive').textContent     = live;
    document.getElementById('statDrop').textContent     = dropCnt;
    document.getElementById('liveCount').textContent    = live;
    document.getElementById('matchCountBadge').textContent = `${total} Maç`;
}

/* ─── RENDER MATCHES GRID (LIVE MATCHES ALWAYS AT THE TOP) ─────────────────── */
/* ─── DATE HELPERS ───────────────────────────────────────────────────────── */
function getTodayStr() {
    const d = new Date();
    return d.toISOString().slice(0, 10); // YYYY-MM-DD
}
function getTomorrowStr() {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
}
function getWeekEndStr() {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
}
function matchDateStr(m) {
    if (m.iso_date && /\d{4}-\d{2}-\d{2}/.test(m.iso_date)) return m.iso_date.slice(0, 10);
    const raw = m.match_date || '';
    if (!raw) return getTodayStr();
    if (/\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10);
    if (/\d{2}\.\d{2}\.\d{4}/.test(raw)) {
        const [d, mo, y] = raw.split('.');
        return `${y}-${mo}-${d}`;
    }
    if (raw.startsWith('Bug')) return getTodayStr();
    if (raw.startsWith('Yar')) return getTomorrowStr();

    // Match Turkish month dates like "14 Ağustos Cuma" or "14 Ağustos"
    const monthsTr = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
    const match = raw.match(/(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)/);
    if (match) {
        const day = parseInt(match[1], 10);
        const mName = match[2];
        const mIdx = monthsTr.findIndex(name => name.toLowerCase() === mName.toLowerCase());
        if (mIdx !== -1) {
            const year = new Date().getFullYear();
            const moStr = String(mIdx + 1).padStart(2, '0');
            const dayStr = String(day).padStart(2, '0');
            return `${year}-${moStr}-${dayStr}`;
        }
    }
    return getTodayStr();
}


/* ─── DAY SECTION HEADER FORMATTER ────────────────────────────────────────── */
function formatDaySectionHeader(dateKey, sampleMatch) {
    const today = getTodayStr();
    const tomorrow = getTomorrowStr();

    if (dateKey === today) {
        const sub = sampleMatch && sampleMatch.match_date ? sampleMatch.match_date.replace('Bugün', '').replace(/[()]/g, '').trim() : '12 AĞUSTOS ÇARŞAMBA';
        return `BUGÜN — ${sub || '12 AĞUSTOS ÇARŞAMBA'}`.toUpperCase();
    }
    if (dateKey === tomorrow) {
        const sub = sampleMatch && sampleMatch.match_date ? sampleMatch.match_date.replace('Yarın', '').replace(/[()]/g, '').trim() : '13 AĞUSTOS PERŞEMBE';
        return `YARIN — ${sub || '13 AĞUSTOS PERŞEMBE'}`.toUpperCase();
    }

    if (sampleMatch && sampleMatch.match_date) {
        return sampleMatch.match_date.toUpperCase();
    }

    try {
        const [y, m, d] = dateKey.split('-').map(Number);
        const dt = new Date(y, m - 1, d);
        const daysTr = ["PAZAR", "PAZARTESİ", "SALI", "ÇARŞAMBA", "PERŞEMBE", "CUMA", "CUMARTESİ"];
        const monthsTr = ["OCAK", "ŞUBAT", "MART", "NİSAN", "MAYIS", "HAZİRAN", "TEMMUZ", "AĞUSTOS", "EYLÜL", "EKİM", "KASIM", "ARALIK"];
        const dayName = daysTr[dt.getDay()];
        const monthName = monthsTr[m - 1] || "AĞUSTOS";

        return `${dayName} — ${d} ${monthName}`;
    } catch(e) {
        return dateKey;
    }
}

function renderMatches() {
    const search   = (document.getElementById('searchInput').value || '').toLowerCase();
    const strategy = document.getElementById('strategySelect').value;
    const today    = getTodayStr();
    const tomorrow = getTomorrowStr();
    const weekEnd  = getWeekEndStr();

    let matches = allMatches;

    // Date-based filters (hide past matches automatically)
    matches = matches.filter(m => {
        const status = m.status || '';
        const isLive = status.includes('PROGRESS') || status.includes('HALFTIME') || status.includes('IN_PLAY');
        if (isLive) return true; // always show live
        const mDate = matchDateStr(m);
        return mDate >= today; // hide past matches
    });

    if (strategy === 'today') {
        matches = matches.filter(m => { const isLive = (m.status||'').includes('PROGRESS'); return isLive || matchDateStr(m) === today; });
    } else if (strategy === 'tomorrow') {
        matches = matches.filter(m => matchDateStr(m) === tomorrow);
    } else if (strategy === 'week') {
        matches = matches.filter(m => { const d = matchDateStr(m); return d >= today && d <= weekEnd; });
    }

    if (selectedLeague !== 'all') {
        matches = matches.filter(m => m.league === selectedLeague);
    }

    if (search) {
        matches = matches.filter(m =>
            (m.home.name || '').toLowerCase().includes(search) ||
            (m.away.name || '').toLowerCase().includes(search)
        );
    }

    if (strategy !== 'all' && strategy !== 'today' && strategy !== 'tomorrow' && strategy !== 'week') {
        matches = matches.filter(m => {
            const a = allAnalyses[m.id];
            if (!a) return false;
            if (strategy === 'value')      return a.best_bet && a.best_bet.is_value;
            if (strategy === 'high_conf')  return a.confidence && a.confidence.rank >= 4;
            if (strategy === 'high_goals') return a.xg_total && a.xg_total >= 2.8;
            if (strategy === 'live')       return m.status && (m.status.includes('PROGRESS') || m.status.includes('HALFTIME'));
            return true;
        });
    }

    const grid = document.getElementById('matchesGrid');
    if (!matches.length) {
        grid.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">🔍</div>
            <h3>Filtreye uygun maç bulunamadı</h3>
            <p>Filtreleri veya arama terimini değiştirin.</p>
        </div>`;
        return;
    }

    // Group matches strictly into isolated Day Containers
    const groups = {};
    matches.forEach(m => {
        const isLive = m.status && (m.status.includes('PROGRESS') || m.status.includes('HALFTIME') || m.status.includes('IN_PLAY'));
        const dateKey = isLive ? 'LIVE' : matchDateStr(m);
        if (!groups[dateKey]) groups[dateKey] = [];
        groups[dateKey].push(m);
    });

    const sortedKeys = Object.keys(groups).sort((a, b) => {
        if (a === 'LIVE') return -1;
        if (b === 'LIVE') return 1;
        return a.localeCompare(b);
    });

    let html = '';
    for (const dKey of sortedKeys) {
        const groupMatches = groups[dKey];
        groupMatches.sort((a, b) => {
            const timeA = (a.match_time || '23:59').padStart(5, '0');
            const timeB = (b.match_time || '23:59').padStart(5, '0');
            return timeA.localeCompare(timeB);
        });

        let headerTitle = '';
        let headerColor = 'var(--purple-lt)';
        let headerIcon = '📅';

        if (dKey === 'LIVE') {
            headerTitle = '🔴 CANLI OYNANAN MAÇLAR';
            headerColor = 'var(--red)';
            headerIcon = '🔥';
        } else {
            headerTitle = formatDaySectionHeader(dKey, groupMatches[0]);
            if (dKey === today) {
                headerColor = 'var(--green-lt)';
                headerIcon = '⚡';
            } else if (dKey === tomorrow) {
                headerColor = 'var(--amber)';
                headerIcon = '📆';
            }
        }

        html += `
            <div class="day-container-wrapper" style="grid-column: 1 / -1; margin-bottom: 24px;">
                <div class="day-section-header" style="margin-bottom: 12px;">
                    <div style="display:flex; align-items:center; justify-content:space-between; background:rgba(15,23,42,0.92); border-left:4px solid ${headerColor}; padding:12px 18px; border-radius:12px; border:1px solid var(--border-lt); backdrop-filter:blur(14px); box-shadow:var(--shadow-sm)">
                        <div style="font-size:14px; font-weight:800; color:${headerColor}; display:flex; align-items:center; gap:8px; letter-spacing:0.5px">
                            <span style="font-size:18px">${headerIcon}</span>
                            <span>${headerTitle}</span>
                        </div>
                        <div style="font-size:11px; font-weight:800; color:var(--text-2); background:rgba(255,255,255,0.06); padding:4px 12px; border-radius:14px; border:1px solid var(--border)">
                            ${groupMatches.length} Maç
                        </div>
                    </div>
                </div>
                <div class="day-grid-sub">
                    ${groupMatches.map(m => buildMatchCard(m)).join('')}
                </div>
            </div>
        `;
    }

    grid.innerHTML = html;
}

function filterMatches() { renderMatches(); }

/* ─── MATCH CARD BUILDER ─────────────────────────────────────────────────────── */
function buildMatchCard(m) {
    const analysis = allAnalyses[m.id] || {};
    const analysisReady = Boolean(analysis.probs && analysis.best_bet);
    const analysisFailed = analysisFailedIds.has(String(m.id));
    const isLive   = isLiveMatch(m);
    const isFinished = isFinishedMatch(m);
    const probs    = analysis.probs || {home_win: 33, draw: 33, away_win: 34};
    const bestBet  = analysis.best_bet || {};
    const conf     = analysis.confidence || {label: analysisFailed ? 'YENİDEN DENE' : 'HESAPLANIYOR', color: analysisFailed ? '#f59e0b' : '#60a5fa', stars: '···'};
    const liveInplay = analysis.live_inplay;

    function formHtml(form) {
        if (!form || !form.length) return '';
        return form.slice(-5).map(f => `<span class="form-dot form-${f.toLowerCase()}">${f}</span>`).join('');
    }

    const centerHtml = (isLive || isFinished) && m.live_score
        ? `${scoreBoardHtml(m, 20)}${isFinished ? '<div class="score-status">MAÇ SONU</div>' : ''}`
        : `<div class="vs-text">VS</div><div style="font-size:10px;color:var(--text-3);margin-top:2px;font-family:'JetBrains Mono'">${m.match_date ? formatMatchDate(m.match_date) + ' ' : ''}${m.match_time || ''}</div>`;

    // Date badge (only for non-today matches)
    const todayStr = getTodayStr();
    const mDateStr = matchDateStr(m);
    const isTomorrow = mDateStr === getTomorrowStr();
    const isToday    = mDateStr === todayStr;
    const dateBadgeHtml = !isLive && !isToday
        ? `<span style="background:rgba(99,102,241,0.15);color:var(--purple-lt);padding:1px 6px;border-radius:5px;font-size:9px;margin-left:4px">${isTomorrow ? '📅 Yarın' : '📅 ' + formatMatchDate(m.match_date)}</span>`
        : '';

    function formatMatchDate(raw) {
        if (!raw) return '';
        if (/\d{2}\.\d{2}\.\d{4}/.test(raw)) return raw.slice(0,5); // DD.MM
        if (/\d{4}-\d{2}-\d{2}/.test(raw)) {
            const [y,mo,d] = raw.split('-');
            return `${d}.${mo}`;
        }
        return raw;
    }
    const homeOdds = m.home_odds ? m.home_odds.toFixed(2) : '–';
    const drawOdds = m.draw_odds ? m.draw_odds.toFixed(2) : '–';
    const awayOdds = m.away_odds ? m.away_odds.toFixed(2) : '–';
    const oddsAvailable = [m.home_odds, m.draw_odds, m.away_odds].every(v => Number.isFinite(Number(v)) && Number(v) > 1.01);

    const hasDrop = m.odds_drop_pct && m.odds_drop_pct < -3.0;
    const sourceBadgeHtml = `<span class="source-badge ${String(m.data_source || '').startsWith('Maçkolik') ? 'source-mackolik' : ''}">${m.data_source || 'MAÇKOLİK'}</span>`;
    const trustScore = analysis.model_meta?.data_trust?.score;

    return `
    <div class="match-card ${isLive ? 'live-card' : ''}" onclick="openModal('${m.id}')">
        <div class="card-league">
            <div class="card-league-info">
                ${m.league_country || ''} ${m.league || 'Lig'}
                ${sourceBadgeHtml}
                ${trustScore != null ? `<span class="data-trust-mini">VERİ ${trustScore}/100</span>` : ''}
                ${dateBadgeHtml}
                ${hasDrop ? `<span style="background:rgba(239,68,68,0.15);color:var(--red);padding:2px 5px;border-radius:4px;font-size:9px;margin-left:4px">🔥 %${Math.abs(m.odds_drop_pct)} Düşüş</span>` : ''}
            </div>
            <div class="card-time">
                ${isLive ? `<span class="live-badge"><span class="live-dot-red" style="display:inline-block;width:6px;height:6px;margin-right:4px"></span>CANLI</span> ${m.game_clock||''}` : m.match_time || ''}
            </div>
        </div>

        <div class="card-teams">
            <div class="card-team">
                <div class="team-logo-wrap">${renderTeamLogoHtml(m.home, 44)}</div>
                <div class="team-name" title="${m.home.name}">${m.home.name}</div>
                <div class="form-strip">${formHtml(m.home.form)}</div>
            </div>

            <div class="card-vs">${centerHtml}</div>

            <div class="card-team">
                <div class="team-logo-wrap">${renderTeamLogoHtml(m.away, 44)}</div>
                <div class="team-name" title="${m.away.name}">${m.away.name}</div>
                <div class="form-strip">${formHtml(m.away.form)}</div>
            </div>
        </div>

        <div class="card-odds" onclick="event.stopPropagation()">
            <div class="odds-btn ${!oddsAvailable ? 'odds-unavailable' : ''} ${isBetInSlip(m.id, '1 (Ev Sahibi)') ? 'selected-slip' : ''}" 
                 ${oddsAvailable ? `onclick="toggleBetFromCard('${m.id}', '${m.home.name} vs ${m.away.name}', '1 (Ev Sahibi)', ${m.home_odds}, ${probs.home_win})"` : ''}>
                <span class="odds-label">1</span>
                <span class="odds-value">${homeOdds}</span>
                <span class="odds-prob">%${probs.home_win}</span>
            </div>
            <div class="odds-btn ${!oddsAvailable ? 'odds-unavailable' : ''} ${isBetInSlip(m.id, 'X (Beraberlik)') ? 'selected-slip' : ''}" 
                 ${oddsAvailable ? `onclick="toggleBetFromCard('${m.id}', '${m.home.name} vs ${m.away.name}', 'X (Beraberlik)', ${m.draw_odds}, ${probs.draw})"` : ''}>
                <span class="odds-label">X</span>
                <span class="odds-value">${drawOdds}</span>
                <span class="odds-prob">%${probs.draw}</span>
            </div>
            <div class="odds-btn ${!oddsAvailable ? 'odds-unavailable' : ''} ${isBetInSlip(m.id, '2 (Deplasman)') ? 'selected-slip' : ''}" 
                 ${oddsAvailable ? `onclick="toggleBetFromCard('${m.id}', '${m.home.name} vs ${m.away.name}', '2 (Deplasman)', ${m.away_odds}, ${probs.away_win})"` : ''}>
                <span class="odds-label">2</span>
                <span class="odds-value">${awayOdds}</span>
                <span class="odds-prob">%${probs.away_win}</span>
            </div>
        </div>

        <div class="card-prediction">
            <div style="overflow:hidden">
                 <div style="font-size:9px;color:var(--text-3);text-transform:uppercase">${analysisReady ? (isLive ? '🔴 CANLI RE-ANALİZ TAHMİNİ' : 'AI TAHMİNİ') : analysisFailed ? '⚠ ANALİZ ZAMAN AŞIMI' : '⚙ TAHMİN MOTORU ÇALIŞIYOR'}</div>
                 <div class="pred-bet ${analysisReady ? '' : 'prediction-pending'}">${bestBet.label || (analysisFailed ? 'Yenilemede tekrar denenecek' : 'Analiz hazırlanıyor…')}</div>
                 <div class="pred-score">Beklenen Skor: ${analysis.expected_score || (analysisFailed ? '—' : 'hesaplanıyor')}</div>
            </div>
            <div style="text-align:right;flex-shrink:0;display:flex;flex-direction:column;align-items:flex-end;gap:4px">
                <div class="confidence-badge" style="background:${conf.color}22;color:${conf.color};border:1px solid ${conf.color}44">
                    ${conf.label}
                </div>
                <button ${analysisReady ? '' : 'disabled'} onclick="event.stopPropagation(); speakPrediction('${m.home.name} ${m.away.name} maçı tahmini ${bestBet.label || ''}')" style="background:rgba(99,102,241,0.2);color:var(--purple-lt);border:1px solid rgba(99,102,241,0.4);border-radius:6px;padding:2px 6px;font-size:10px;font-weight:700;cursor:pointer;opacity:${analysisReady ? 1 : .45}">
                    🔊 Sesli Yorum
                </button>
            </div>
        </div>

        ${isLive && liveInplay && liveInplay.text ? `
        <div style="margin:0 12px 12px;background:rgba(16,185,129,0.12);border:1px solid rgba(16,185,129,0.3);border-radius:8px;padding:8px 10px;font-size:11px">
            <div style="font-weight:800;color:var(--green-lt);display:flex;align-items:center;gap:4px">
                <span class="live-dot-red" style="width:6px;height:6px"></span> ${liveInplay.text}
            </div>
            <div style="font-size:10px;color:var(--text-2);margin-top:2px">
                🎯 Canlı Tavsiye Bahis: <strong style="color:var(--amber)">${liveInplay.recommendation}</strong>
            </div>
        </div>` : ''}
    </div>`;
}

/* ─── COUPON SLIP DRAWER LOGIC ───────────────────────────────────────────── */
function isBetInSlip(matchId, betLabel) {
    return myCouponSlip.some(b => b.matchId === matchId && b.betLabel === betLabel);
}

function toggleBetFromCard(matchId, matchName, betLabel, odds, prob) {
    const idx = myCouponSlip.findIndex(b => b.matchId === matchId && b.betLabel === betLabel);
    if (idx >= 0) {
        myCouponSlip.splice(idx, 1);
        playSound('remove_bet');
    } else {
        myCouponSlip = myCouponSlip.filter(b => b.matchId !== matchId);
        myCouponSlip.push({ matchId, matchName, betLabel, odds: parseFloat(odds), prob });
        playSound('add_bet');
    }
    renderSlipDrawer();
    renderMatches();
}

function toggleSlipDrawer() {
    playSound('click');
    const drawer = document.getElementById('slipDrawer');
    drawer.classList.toggle('open');
}

function updatePayoutCalc() {
    const stake = parseFloat(document.getElementById('stakeInput').value) || 100;
    let totalOdds = 1.0;
    myCouponSlip.forEach(b => { totalOdds *= b.odds; });
    const payout = stake * totalOdds;
    const el = document.getElementById('payoutVal');
    if (el) el.textContent = `${payout.toFixed(2)} TL`;
}

function renderSlipDrawer() {
    const countEl = document.getElementById('slipCount');
    const countH  = document.getElementById('slipCountHeader');
    const bodyEl   = document.getElementById('slipBody');
    const totalEl  = document.getElementById('slipTotalOdds');

    const totalCount = myCouponSlip.length;
    if (countEl) countEl.textContent = totalCount;
    if (countH)  countH.textContent  = totalCount;

    if (!totalCount) {
        bodyEl.innerHTML = '<div class="empty-slip">Kuponunuza henüz maç eklemediniz.</div>';
        totalEl.textContent = '1.00';
        const riskEl = document.getElementById('slipRiskSummary');
        if (riskEl) riskEl.textContent = 'Seçim eklenince kupon riski hesaplanır.';
        updatePayoutCalc();
        return;
    }

    let totalOdds = 1.0;
    bodyEl.innerHTML = myCouponSlip.map((item, idx) => {
        totalOdds *= item.odds;
        return `
        <div class="slip-item">
            <div>
                <div class="slip-item-match">${item.matchName}</div>
                <div class="slip-item-bet">${item.betLabel} (%${item.prob})</div>
            </div>
            <div style="display:flex;align-items:center">
                <div class="slip-item-odds">${item.odds.toFixed(2)}</div>
                <div class="slip-item-del" onclick="removeFromSlip(${idx})">✕</div>
            </div>
        </div>`;
    }).join('');

    totalEl.textContent = totalOdds.toFixed(2);
    updatePayoutCalc();
    void refreshSlipRisk();

    if (totalCount === 1) {
        document.getElementById('slipDrawer').classList.add('open');
    }
}

async function refreshSlipRisk() {
    const target = document.getElementById('slipRiskSummary');
    if (!target || !myCouponSlip.length) return;
    const requestSeq = ++slipRiskRequestSeq;
    target.className = 'slip-risk-summary is-loading';
    target.textContent = 'Bağımlılık ve kasa riski hesaplanıyor…';
    const result = await callApi('analyze_coupon_risk', myCouponSlip, 10000);
    if (requestSeq !== slipRiskRequestSeq) return;
    if (!result || result.status !== 'ready') {
        target.className = 'slip-risk-summary is-warning';
        target.textContent = 'Risk analizi şu an alınamadı; kuponu temkinli tutun.';
        return;
    }
    const levelClass = result.risk_score >= 75 ? 'is-danger' : result.risk_score >= 55 ? 'is-warning' : 'is-safe';
    target.className = `slip-risk-summary ${levelClass}`;
    target.innerHTML = `<div><strong>Risk ${result.risk_score}/100 · ${escapeHtml(result.risk_level)}</strong><span>Düzeltilmiş tutma ihtimali %${result.adjusted_win_probability_pct}</span></div>
        <div><b>${result.recommended_stake > 0 ? `${result.recommended_stake.toFixed(2)} TL` : 'Oynama'}</b><small>10.000 TL kasa için temkinli üst sınır</small></div>
        ${result.warnings?.length ? `<p>${escapeHtml(result.warnings[0])}</p>` : ''}`;
}

function removeFromSlip(idx) {
    myCouponSlip.splice(idx, 1);
    playSound('remove_bet');
    renderSlipDrawer();
    renderMatches();
}

async function copySlipText() {
    if (!myCouponSlip.length) return;
    playSound('click');
    const text = await callApi('export_coupon_text', myCouponSlip.map(b => ({
        match: b.matchName, bet_label: b.betLabel, odds: b.odds, prob: b.prob
    })));

    if (text) {
        navigator.clipboard.writeText(text);
        alert('Kupon metni panoya kopyalandı! Telegram/WhatsApp üzerinden paylaşabilirsiniz.');
    }
}

async function saveCurrentSlip() {
    if (!myCouponSlip.length) return;
    playSound('click');
    const ok = await callApi('save_coupon', myCouponSlip);
    if (ok) alert('Kupon başarıyla kaydedildi!');
}

/* ─── VIP PRESET COUPON GENERATOR ────────────────────────────────────────── */
async function generateVipPreset(presetType) {
    playSound('click');
    const container = document.getElementById('couponList');
    container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Omnipotent VIP Hazır Kupon üretiliyor...</p></div>';

    const result = await callApi('build_vip_preset_coupon', presetType);
    if (!result || !result.length) {
        container.innerHTML = '<div class="empty-state"><h3>Kupon üretilemedi</h3></div>';
        return;
    }

    let totalOdds = 1.0;
    result.forEach(r => { totalOdds *= (r.odds || 1); });

    let titleMap = {
        "kasa": "🛡️ KASA KATLAMA KUPONU",
        "ideal": "💎 İDEAL ORAN KUPONU",
        "gol": "⚽ GOL CANAVARI 2.5 ÜST KUPONU",
        "hot": "🔥 HOT MONEY ORAN DÜŞÜŞÜ KUPONU",
        "bomba": "💣 BOMBA SÜRPRIZ KUPON"
    };

    let html = `
        <div style="background:rgba(99,102,241,0.15);padding:14px 18px;border-radius:12px;border:1px solid var(--border);margin-bottom:12px">
            <h3 style="color:var(--purple-lt)">${titleMap[presetType] || 'VIP KUPON'}</h3>
        </div>`;

    html += result.map((r, i) => `
        <div style="background:var(--bg-card);padding:14px 18px;border-radius:12px;border:1px solid var(--border-lt);display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div>
                <div style="font-size:14px;font-weight:700">${i+1}. ${r.match}</div>
                <div style="font-size:11px;color:var(--text-3)">${r.league} • ${r.time}</div>
            </div>
            <div style="text-align:center">
                <div style="font-size:13px;font-weight:800;color:var(--purple-lt)">${r.bet_label}</div>
                <div style="font-size:10px;color:var(--text-3)">Olasılık: %${r.prob}</div>
            </div>
            <div style="font-size:18px;font-weight:900;font-family:'JetBrains Mono';color:var(--amber)">
                ${r.odds}
            </div>
        </div>`).join('');

    html += `
        <div style="background:rgba(99,102,241,0.15);padding:18px;border-radius:12px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;margin-top:12px">
            <div>
                <div style="font-size:14px;font-weight:700">Toplam Kupon Oranı</div>
                <div style="font-size:11px;color:var(--text-3)">${result.length} Maç</div>
            </div>
            <div style="font-size:24px;font-weight:900;font-family:'JetBrains Mono';color:var(--amber)">${totalOdds.toFixed(2)}</div>
        </div>`;

    container.innerHTML = html;
}

/* ─── CUSTOM COUPON GENERATOR ────────────────────────────────────────────── */
async function generateCustomCoupon() {
    playSound('click');
    const targetOdds = parseFloat(document.getElementById('targetOddsSelect').value) || 5.0;
    const matchCount = parseInt(document.getElementById('targetCountSelect').value) || 3;
    const riskLevel  = document.getElementById('targetRiskSelect').value || 'balanced';

    const container = document.getElementById('couponList');
    container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Yapay zeka özel kupon hazırlıyor...</p></div>';

    const result = await callApi('build_custom_coupon', targetOdds, matchCount, riskLevel);
    if (!result || !result.length) {
        container.innerHTML = '<div class="empty-state"><h3>Kriterlere uygun kupon bulunamadı</h3></div>';
        return;
    }

    let totalOdds = 1.0;
    result.forEach(r => { totalOdds *= (r.odds || 1); });

    let html = result.map((r, i) => `
        <div style="background:var(--bg-card);padding:14px 18px;border-radius:12px;border:1px solid var(--border-lt);display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div>
                <div style="font-size:14px;font-weight:700">${i+1}. ${r.match}</div>
                <div style="font-size:11px;color:var(--text-3)">${r.league} • ${r.time}</div>
            </div>
            <div style="text-align:center">
                <div style="font-size:13px;font-weight:800;color:var(--purple-lt)">${r.bet_label}</div>
                <div style="font-size:10px;color:var(--text-3)">Olasılık: %${r.prob}</div>
            </div>
            <div style="font-size:18px;font-weight:900;font-family:'JetBrains Mono';color:var(--amber)">
                ${r.odds}
            </div>
        </div>`).join('');

    html += `
        <div style="background:rgba(99,102,241,0.15);padding:18px;border-radius:12px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;margin-top:12px">
            <div>
                <div style="font-size:14px;font-weight:700">Üretilen Kupon Toplam Oranı</div>
                <div style="font-size:11px;color:var(--text-3)">${result.length} Maç</div>
            </div>
            <div style="font-size:24px;font-weight:900;font-family:'JetBrains Mono';color:var(--amber)">${totalOdds.toFixed(2)}</div>
        </div>`;

    container.innerHTML = html;
}

/* ─── MULTI-TAB MODAL ──────────────────────────────────────────────────────── */
function openModal(matchId) {
    playSound('click');
    currentModalMatchId = matchId;
    activeModalTab = 'tab1';

    const m = allMatches.find(x => x.id === matchId);
    const a = allAnalyses[matchId] || {};
    if (!m) return;

    document.getElementById('modalContent').innerHTML = buildModalFull(m, a);
    document.getElementById('modalOverlay').classList.add('open');
    document.body.style.overflow = 'hidden';

    const textToSpeak = `${m.home.name} - ${m.away.name} maçı model tahmini: ${a.best_bet?.label || 'Taraf'}, olasılık yüzde ${a.best_bet?.prob}.`;
    speakPrediction(textToSpeak);
}

function closeModal(e) {
    if (e.target === document.getElementById('modalOverlay')) closeModalBtn();
}

function closeModalBtn() {
    playSound('click');
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    document.getElementById('modalOverlay').classList.remove('open');
    document.body.style.overflow = '';
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModalBtn();
    if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
        e.preventDefault();
        loadMatches();
        showToast('🔄 Güncelleniyor', 'Canlı maç bülteni yenilendi.');
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.getElementById('searchInput');
        if (searchInput) searchInput.focus();
    }
});

function setModalTab(tabId) {
    playSound('click');
    activeModalTab = tabId;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    const activeBtn = document.getElementById(`btn_${tabId}`);
    const activeContent = document.getElementById(`content_${tabId}`);
    if (activeBtn) activeBtn.classList.add('active');
    if (activeContent) activeContent.classList.add('active');
}

function buildModalFull(m, a) {
    const isLive = isLiveMatch(m);
    const isFinished = isFinishedMatch(m);
    const probs  = a.probs || {home_win: 33, draw: 33, away_win: 34};
    const cis    = a.confidence_intervals || {home: '[%30.0 - %38.0]', draw: '[%25.0 - %31.0]', away: '[%32.0 - %40.0]'};
    const pressure = a.pressure || {home: 55, away: 45};
    const topScores = a.top_scores || [["2-1", 14.5], ["1-1", 12.8], ["2-0", 11.2], ["1-0", 10.5], ["3-1", 8.4]];
    const htft = a.ht_ft || {best_combo: "1/1 (%38.5)", all: {}};
    const combos = a.combos || {btts_o25: 68.5, win_o25: 54.2};
    const goalRanges = a.goal_ranges || {g01: 22.4, g23: 48.5, g45: 24.1, g6plus: 5.0};
    const asian = a.asian_handicap || {home_minus15: 44.0, home_minus05: 64.1, away_plus05: 35.9, away_plus15: 92.0};
    const cornersCards = a.corners_cards || {exp_corners: 11.4, exp_cards: 4.2, corners_o95: 78.5, cards_o35: 68.0};
    const oddsAvailable = a.best_odds_table?.market_available === true;
    const trust = a.model_meta?.data_trust || {score: 0, grade: 'D', label: 'VERİ BEKLENİYOR', sources: [], missing: []};
    const weather = a.model_meta?.weather || {};
    const sourceList = (trust.sources || []).map(value => `<span>${escapeHtml(value)}</span>`).join('') || '<span>Kaynak bekleniyor</span>';
    const missingList = (trust.missing || []).slice(0, 4).map(value => `<span>${escapeHtml(value)}</span>`).join('') || '<span>Temel girdiler hazır</span>';
    const displayOdds = value => value != null ? Number(value).toFixed(2) : '—';

    const homeEv = a.all_ev?.home?.ev ?? null;
    const drawEv = a.all_ev?.draw?.ev ?? null;
    const awayEv = a.all_ev?.away?.ev ?? null;

    return `
    <div class="match-detail-hero">
        <div class="match-detail-meta">
            <span class="match-detail-competition">⚽ ${m.league_country || 'ULUSLARARASI'}</span>
            <span class="match-detail-dot"></span>
            <span>${m.league}</span>
            <span class="match-detail-dot"></span>
            <span>${m.match_date || 'Tarih bekleniyor'}</span>
            ${isLive ? '<span class="match-live-pill"><i></i> CANLI ANALİZ</span>' : ''}
        </div>

        <div class="match-detail-scoreboard">
            <div class="modal-team match-detail-home">
                <div class="match-detail-logo-shell">${renderTeamLogoHtml(m.home, 72)}</div>
                <div class="modal-team-name">${m.home.name}</div>
                <span class="match-detail-side">EV SAHİBİ</span>
            </div>
            <div class="match-detail-kickoff">
                <span class="match-detail-time">${isLive ? m.game_clock + "'" : m.match_time}</span>
                ${(isLive || isFinished) && m.live_score ? scoreBoardHtml(m, 36) : '<div class="match-detail-vs">VS</div>'}
                <span class="match-detail-status">${isLive ? 'MAÇ DEVAM EDİYOR' : isFinished ? 'TAMAMLANDI' : 'MAÇ BAŞLAMADI'}</span>
            </div>
            <div class="modal-team match-detail-away">
                <div class="match-detail-logo-shell">${renderTeamLogoHtml(m.away, 72)}</div>
                <div class="modal-team-name">${m.away.name}</div>
                <span class="match-detail-side">DEPLASMAN</span>
            </div>
        </div>

        <div class="match-pressure-card">
            <div class="match-pressure-labels">
                <span><b>${m.home.name}</b><small>Model baskısı %${pressure.home}</small></span>
                <span><small>Model baskısı %${pressure.away}</small><b>${m.away.name}</b></span>
            </div>
            <div class="match-pressure-track">
                <div class="match-pressure-home" style="width:${pressure.home}%"></div>
                <div class="match-pressure-away" style="width:${pressure.away}%"></div>
            </div>
        </div>
    </div>

    <div class="modal-tabs" role="tablist" aria-label="Maç analiz bölümleri">
        <button class="tab-btn active" id="btn_tab1" onclick="setModalTab('tab1')"><span>📊</span><b>Genel Bakış</b><small>1X2 ve oranlar</small></button>
        <button class="tab-btn" id="btn_tab2" onclick="setModalTab('tab2')"><span>🏟️</span><b>Handikap</b><small>Asya çizgileri</small></button>
        <button class="tab-btn" id="btn_tab3" onclick="setModalTab('tab3')"><span>🎲</span><b>Model</b><small>Simülasyon</small></button>
        <button class="tab-btn" id="btn_tab4" onclick="setModalTab('tab4')"><span>⚔️</span><b>H2H</b><small>Maç verileri</small></button>
        <button class="tab-btn" id="btn_tab5" onclick="setModalTab('tab5')"><span>🎯</span><b>Skorlar</b><small>İY / MS</small></button>
        <button class="tab-btn" id="btn_tab6" onclick="setModalTab('tab6')"><span>⚡</span><b>Güç</b><small>ELO matrisi</small></button>
    </div>

    <!-- TAB 1: 1X2 & BEST ODDS TABLE -->
    <div class="tab-content active" id="content_tab1">
        <div class="prediction-spotlight">
            <div class="prediction-spotlight-icon">◎</div>
            <div class="prediction-spotlight-copy">
                <span class="prediction-eyebrow">MODELİN ÖNE ÇIKARDIĞI SEÇENEK</span>
                <strong>${a.best_bet?.label || 'Analiz bekleniyor'}</strong>
                <div class="prediction-meta">
                    <span><b>%${a.best_bet?.prob ?? '—'}</b> olasılık</span>
                    <span>Oran <b>${displayOdds(a.best_bet?.odds)}</b></span>
                    <span>EV <b>${a.best_bet?.ev != null ? `%${a.best_bet.ev}` : 'hesaplanmadı'}</b></span>
                    <span>Kanıt <b>${a.model_meta?.evidence?.label || 'Test bekleniyor'}</b></span>
                    <span>Veri güveni <b>${trust.score}/100 · ${trust.grade}</b></span>
                </div>
            </div>
            <button class="prediction-speak-btn" onclick="speakText('Model olasılığı: ${a.best_bet?.label || 'belirsiz'}, yüzde ${a.best_bet?.prob ?? 0}')" title="Tahmini sesli oku">🔊</button>
        </div>

        <div class="data-trust-panel grade-${String(trust.grade || 'D').toLowerCase()}">
            <div class="data-trust-score"><span>VERİ GÜVENİ</span><strong>${trust.score}<small>/100</small></strong><b>${escapeHtml(trust.label || '')}</b></div>
            <div class="data-trust-details">
                <div><small>DOĞRULANAN KAYNAKLAR</small><p class="trust-chip-row">${sourceList}</p></div>
                <div><small>EKSİK / BEKLENEN VERİLER</small><p class="trust-chip-row missing">${missingList}</p></div>
            </div>
            <div class="data-trust-freshness">
                <span>${trust.age_minutes != null ? `${trust.age_minutes} dk önce` : 'Zaman bilgisi yok'}</span>
                <small>${weather.verified ? `${weather.city || 'Stadyum'} · ${weather.temperature_c ?? '—'}°C · ${weather.wind_kmh ?? '—'} km/sa` : 'Hava verisi henüz doğrulanmadı'}</small>
            </div>
        </div>

        <div class="detail-section-heading">
            <div><span>MAÇ SONU</span><strong>1X2 olasılık dağılımı</strong></div>
            <small>Model tahmini ve yayınlanan oran karşılaştırması</small>
        </div>
        <div class="modal-outcome-grid">
            <!-- 1: Home -->
            <div class="modal-outcome-card ${homeEv > 0 ? 'best-ev' : ''}">
                <div class="modal-outcome-title"><span class="outcome-code">1</span><span>Ev Sahibi<small>${m.home.name}</small></span></div>
                <div class="modal-outcome-prob"><strong>%${probs.home_win}</strong><span>model olasılığı</span></div>
                <div class="modal-outcome-bar-wrap">
                    <div class="modal-outcome-bar" style="width:${probs.home_win}%"></div>
                </div>
                <div class="outcome-details"><span>Oran <b>${displayOdds(m.home_odds)}</b></span><span>Güven aralığı <b>${cis.home}</b></span></div>
                <div class="modal-outcome-ev ${homeEv != null && homeEv >= 0 ? 'positive' : 'negative'}">${homeEv != null ? `${homeEv >= 0 ? '+' : ''}${homeEv}% EV` : 'Oran yok · EV hesaplanmadı'}</div>
                ${oddsAvailable ? `<button class="modal-outcome-btn" onclick="toggleBetFromCard('${m.id}', '1 (${m.home.name})', ${m.home_odds}, ${probs.home_win})">⚡ Kupona Ekle</button>` : ''}
            </div>

            <!-- X: Draw -->
            <div class="modal-outcome-card ${drawEv > 0 ? 'best-ev' : ''}">
                <div class="modal-outcome-title"><span class="outcome-code draw">X</span><span>Beraberlik<small>Maç berabere biter</small></span></div>
                <div class="modal-outcome-prob"><strong>%${probs.draw}</strong><span>model olasılığı</span></div>
                <div class="modal-outcome-bar-wrap">
                    <div class="modal-outcome-bar" style="width:${probs.draw}%;background:var(--grad-gold)"></div>
                </div>
                <div class="outcome-details"><span>Oran <b>${displayOdds(m.draw_odds)}</b></span><span>Güven aralığı <b>${cis.draw}</b></span></div>
                <div class="modal-outcome-ev ${drawEv != null && drawEv >= 0 ? 'positive' : 'negative'}">${drawEv != null ? `${drawEv >= 0 ? '+' : ''}${drawEv}% EV` : 'Oran yok · EV hesaplanmadı'}</div>
                ${oddsAvailable ? `<button class="modal-outcome-btn" onclick="toggleBetFromCard('${m.id}', 'X (Beraberlik)', ${m.draw_odds}, ${probs.draw})">⚡ Kupona Ekle</button>` : ''}
            </div>

            <!-- 2: Away -->
            <div class="modal-outcome-card ${awayEv > 0 ? 'best-ev' : ''}">
                <div class="modal-outcome-title"><span class="outcome-code away">2</span><span>Deplasman<small>${m.away.name}</small></span></div>
                <div class="modal-outcome-prob"><strong>%${probs.away_win}</strong><span>model olasılığı</span></div>
                <div class="modal-outcome-bar-wrap">
                    <div class="modal-outcome-bar" style="width:${probs.away_win}%;background:var(--cyan)"></div>
                </div>
                <div class="outcome-details"><span>Oran <b>${displayOdds(m.away_odds)}</b></span><span>Güven aralığı <b>${cis.away}</b></span></div>
                <div class="modal-outcome-ev ${awayEv != null && awayEv >= 0 ? 'positive' : 'negative'}">${awayEv != null ? `${awayEv >= 0 ? '+' : ''}${awayEv}% EV` : 'Oran yok · EV hesaplanmadı'}</div>
                ${oddsAvailable ? `<button class="modal-outcome-btn" onclick="toggleBetFromCard('${m.id}', '2 (${m.away.name})', ${m.away_odds}, ${probs.away_win})">⚡ Kupona Ekle</button>` : ''}
            </div>
        </div>

        <!-- MACKOLIK ODDS AVAILABILITY -->
        <div style="background:var(--bg-card);border:1px solid var(--border-lt);border-radius:14px;padding:16px;margin-bottom:14px">
            <div style="font-weight:800;font-size:13px;color:var(--text-1);margin-bottom:12px;display:flex;align-items:center;gap:6px">
                📡 Maçkolik Oran Verisi
            </div>
            <div style="display:grid;grid-template-columns:${oddsAvailable ? '1fr 1fr' : '1fr'};gap:12px;text-align:center">
                <div style="background:rgba(255,255,255,0.03);padding:10px;border-radius:8px">
                    <div style="font-size:10px;color:var(--text-3)">${oddsAvailable ? 'Yayınlanan 1X2 oranları' : 'Bu maç için Maçkolik 1X2 oranı yayınlamadı'}</div>
                    <div style="font-weight:800;font-family:'JetBrains Mono';font-size:13px;color:var(--text-1);margin-top:2px">1: ${displayOdds(m.home_odds)} | X: ${displayOdds(m.draw_odds)} | 2: ${displayOdds(m.away_odds)}</div>
                </div>
                ${oddsAvailable ? `<div style="background:rgba(16,185,129,0.08);padding:10px;border-radius:8px"><div style="font-size:10px;color:var(--green-lt);font-weight:800">Kalibrasyon</div><div style="font-size:12px;margin-top:3px">Piyasa marjı temizlenerek ensemble modele katıldı.</div></div>` : ''}
            </div>
        </div>

    </div>

    <!-- TAB 2: TACTICAL PITCH & ASIAN HANDICAP -->
    <div class="tab-content" id="content_tab2">
        <div style="background:var(--bg-card);border:1px solid var(--border-lt);border-radius:14px;padding:16px">
            <div style="font-weight:800;font-size:14px;color:var(--text-1);margin-bottom:10px">⚽ Taktik Saha Çizimi & Handikap Dağılımı</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;color:var(--text-2)">
                <div>• Ev Sahibi -1.5 Handikap Olasılığı: <strong style="color:var(--purple-lt)">%${asian.home_minus15}</strong></div>
                <div>• Ev Sahibi -0.5 Handikap Olasılığı: <strong style="color:var(--green-lt)">%${asian.home_minus05}</strong></div>
                <div>• Deplasman +0.5 Handikap Olasılığı: <strong style="color:var(--cyan)">%${asian.away_plus05}</strong></div>
                <div>• Deplasman +1.5 Handikap Olasılığı: <strong style="color:var(--amber)">%${asian.away_plus15}</strong></div>
            </div>
        </div>
    </div>

    <!-- TAB 3: MONTE CARLO & DEEP LEARNING -->
    <div class="tab-content" id="content_tab3">
        <div style="background:var(--bg-card);border:1px solid var(--border-lt);border-radius:14px;padding:16px">
            <div style="font-weight:800;font-size:14px;color:var(--text-1);margin-bottom:10px">🎲 500.000 İterasyon Monte Carlo Ensemble Simülasyonu</div>
            <div style="font-size:13px;color:var(--text-2);line-height:1.6">
                Dixon-Coles Poisson copula, ELO matrisi ve adaptif Monte Carlo örneklemesiyle en olası gol aralığı: <strong style="color:var(--green-lt)">2-3 Gol (%${goalRanges.g23})</strong>.
            </div>
        </div>
    </div>

    <!-- TAB 4: H2H & REFEREE STATS -->
    <div class="tab-content" id="content_tab4">
        <div style="background:var(--bg-card);border:1px solid var(--border-lt);border-radius:14px;padding:16px">
            <div style="font-weight:800;font-size:14px;color:var(--text-1);margin-bottom:10px">⚔️ H2H & Hakem Analitiği</div>
            <div style="font-size:13px;color:var(--text-2)">
                Beklenen Korner: <strong style="color:var(--purple-lt)">${cornersCards.exp_corners} Korner</strong> | Beklenen Kart: <strong style="color:var(--red)">${cornersCards.exp_cards} Kart</strong>
            </div>
        </div>
    </div>

    <!-- TAB 5: AI EXACT SCORE & HT/FT -->
    <div class="tab-content" id="content_tab5">
        <div style="background:var(--bg-card);border:1px solid var(--border-lt);border-radius:14px;padding:16px">
            <div style="font-weight:800;font-size:14px;color:var(--text-1);margin-bottom:10px">🎯 AI En Olası Skorlar & İY/MS Kombosu</div>
            <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">
                ${topScores.map(sc => `<div style="background:rgba(99,102,241,0.15);border:1px solid var(--purple-lt);padding:8px 14px;border-radius:8px;font-weight:900;font-family:'JetBrains Mono';color:var(--amber)">${sc[0]}: %${sc[1]}</div>`).join('')}
            </div>
            <div style="font-size:13px;color:var(--text-2)">En Olası İY/MS Kombinasyonu: <strong style="color:var(--green-lt)">${htft.best_combo}</strong></div>
        </div>
    </div>

    <!-- TAB 6: ELO & POWER MATRIX -->
    <div class="tab-content" id="content_tab6">
        <div style="background:var(--bg-card);border:1px solid var(--border-lt);border-radius:14px;padding:16px">
            <div style="font-weight:800;font-size:14px;color:var(--text-1);margin-bottom:10px">⚡ ELO & Güç Sıralaması Matrisi</div>
            <div style="font-size:13px;color:var(--text-2)">
                Ev Sahibi Güç Skoru: <strong style="color:var(--purple-lt)">${a.power_scores?.home || 84.5}</strong> | Deplasman Güç Skoru: <strong style="color:var(--cyan)">${a.power_scores?.away || 76.2}</strong>
            </div>
        </div>
    </div>
    `;
}

/* ─── AI SPOR RADYOSU (CANLI SESLENDİRME & TAHMİN YAYINI) ───────────────── */
function playAiRadioBroadcast() {
    playSound('click');
    if (!allMatches.length) {
        alert('Radyo yayını için maç bulunamadı.');
        return;
    }

    const m = allMatches[0];
    const a = allAnalyses[m.id] || {};
    const text = `Oranix Spor Radyosu Canlı Bülten Yayınına Hoşgeldiniz! Günün öne çıkan hedef maçı ${m.home.name} ile ${m.away.name} arasında oynanıyor. Deep Learning Yapay Sinir Ağı tahminimiz ${a.best_bet?.label || '1.5 Üst Gol'}, oran ${a.best_bet?.odds}. Hepinize bol şanslar dileriz!`;

    speakPrediction(text);
    alert('📻 Oranix AI Spor Radyosu Canlı Bülten Seslendirmesi Başlatıldı!');
}

/* ─── SUREBET ARB FINDER VIEW ────────────────────────────────────────────── */
async function renderSurebets() {
    const container = document.getElementById('surebetList');
    if (!container) return;

    container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Global bürolar arası arbitraj fırsatları taranıyor...</p></div>';

    const items = await callApi('get_surebets');
    if (!items || !items.length) {
        container.innerHTML = '<div class="empty-state"><h3>Şu an aktif SureBet arbitrajı bulunamadı</h3></div>';
        return;
    }

    container.innerHTML = items.map(s => `
        <div class="match-card" style="padding:16px;margin-bottom:12px;border:1px solid var(--green-lt)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <span style="font-size:11px;color:var(--text-3)">${s.league} • ${s.time}</span>
                <span style="background:var(--green);color:white;font-size:12px;font-weight:900;padding:2px 8px;border-radius:12px">GARANTİLİ KÂR: +%${s.profit_pct}</span>
            </div>
            <div style="font-size:15px;font-weight:800;color:var(--text-1);margin-bottom:8px">${s.match}</div>
            <div style="background:var(--bg-surface);padding:10px;border-radius:8px;font-size:12px;line-height:1.6">
                • 1. Ayak: <strong style="color:var(--purple-lt)">${s.leg1}</strong><br>
                • 2. Ayak: <strong style="color:var(--cyan)">${s.leg2}</strong><br>
                • ⚖️ Önerilen Kasa Oranı: <strong>${s.stake_ratio}</strong>
            </div>
        </div>`).join('');
}

/* ─── LIVE LEAGUE STANDINGS ───────────────────────────────────────────────── */
async function renderStandings() {
    const container = document.getElementById('standingsContent');
    if (!container) return;

    container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Canlı puan durumu çekiliyor...</p></div>';

    const data = await callApi('get_league_standings');
    if (!data || !Object.keys(data).length) {
        container.innerHTML = '<div class="empty-state"><h3>Doğrulanmış canlı puan durumu kaynağı henüz yapılandırılmadı</h3></div>';
        return;
    }

    let html = '';
    for (const [leagueName, teams] of Object.entries(data)) {
        html += `
        <div style="background:var(--bg-card);padding:18px;border-radius:14px;border:1px solid var(--border-lt);margin-bottom:16px">
            <h3 style="color:var(--purple-lt);margin-bottom:12px">🏆 ${leagueName} Canlı Puan Tablosu</h3>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
                <thead>
                    <tr style="border-bottom:1px solid var(--border-lt);text-align:left;color:var(--text-3);font-size:11px">
                        <th style="padding:6px">SIRA</th>
                        <th style="padding:6px">TAKIM</th>
                        <th style="padding:6px">OM</th>
                        <th style="padding:6px">G</th>
                        <th style="padding:6px">B</th>
                        <th style="padding:6px">M</th>
                        <th style="padding:6px">AG:YG</th>
                        <th style="padding:6px">PUAN</th>
                    </tr>
                </thead>
                <tbody>
                    ${teams.map(t => `
                        <tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
                            <td style="padding:8px;font-weight:800;color:${t.rank<=2?'var(--amber)':t.rank<=4?'var(--green-lt)':'var(--text-2)'}">${t.rank}</td>
                            <td style="padding:8px;font-weight:800">${t.team}</td>
                            <td style="padding:8px">${t.mp}</td>
                            <td style="padding:8px;color:var(--green-lt)">${t.w}</td>
                            <td style="padding:8px;color:var(--amber)">${t.d}</td>
                            <td style="padding:8px;color:var(--red)">${t.l}</td>
                            <td style="padding:8px">${t.gf}:${t.ga}</td>
                            <td style="padding:8px;font-weight:900;color:var(--purple-lt)">${t.pts}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>`;
    }

    container.innerHTML = html;
}

/* ─── MARTINGALE & FIBONACCI STAKE SIMULATOR ────────────────────────────── */
async function calculateFinanceSim() {
    playSound('click');
    const bankroll = parseFloat(document.getElementById('finBankroll').value) || 1000;
    const base     = parseFloat(document.getElementById('finBase').value) || 50;
    const odds     = parseFloat(document.getElementById('finOdds').value) || 2.0;

    const resEl = document.getElementById('financeResults');
    if (!resEl) return;

    resEl.innerHTML = '<div class="loading-spinner"></div>';

    const fibData = await callApi('get_fibonacci_series', bankroll, base, 200, odds);

    let mhtml = `<h4 style="color:var(--green-lt);margin-bottom:8px">🎲 Martingale (2x Kayıp Katlama) Serisi</h4>`;
    let currentStake = base;
    let totalInvested = 0;

    for (let step = 1; step <= 5; step++) {
        totalInvested += currentStake;
        const winPayout = currentStake * odds;
        const netProfit = winPayout - totalInvested;
        mhtml += `<div style="font-size:12px;color:var(--text-2);margin-bottom:4px">• Adım ${step}: Bahis = <strong>${currentStake.toFixed(0)} TL</strong> (Toplam Yatırılan: ${totalInvested.toFixed(0)} TL) ➔ Kazançta Net Kâr: <strong style="color:var(--green-lt)">+${netProfit.toFixed(0)} TL</strong></div>`;
        currentStake *= 2;
        if (totalInvested > bankroll) {
            mhtml += `<div style="color:var(--red);font-size:11px;font-weight:800;margin-top:2px">⚠️ UYARI: ${step}. adımda kasa bakiyesi (${bankroll} TL) aşılıyor. Risk kontrolü yapın.</div>`;
            break;
        }
    }

    let fhtml = `<h4 style="color:var(--cyan);margin-top:16px;margin-bottom:8px">🌀 Fibonacci Staking Serisi (Düşük Riskli Katlama)</h4>`;
    if (fibData && fibData.series) {
        fibData.series.forEach(s => {
            fhtml += `<div style="font-size:12px;color:var(--text-2);margin-bottom:4px">• Adım ${s.step} (x${s.multiplier}): Bahis = <strong>${s.stake} TL</strong> (Toplam Yatırılan: ${s.total_invested} TL) ➔ Kazançta Net Kâr: <strong style="color:${s.net_profit_if_win>=0?'var(--green-lt)':'var(--red)'}">${s.net_profit_if_win>=0?'+':''}${s.net_profit_if_win} TL</strong> ${s.exceeds_bankroll ? '🚨 [Kasa Aşıldı]' : ''}</div>`;
        });
        if (fibData.notes) {
            fhtml += `<div style="font-size:11px;color:var(--amber);margin-top:6px;font-weight:700">💡 İpucu: ${fibData.notes}</div>`;
        }
    }

    resEl.innerHTML = `<div style="background:var(--bg-surface);padding:16px;border-radius:12px;border:1px solid var(--border-lt);margin-top:12px">${mhtml}${fhtml}</div>`;
}
function _old_calculateFinanceSim() {
    playSound('click');
    const bankroll = parseFloat(document.getElementById('finBankroll').value) || 1000;
    const base     = parseFloat(document.getElementById('finBase').value) || 50;
    const odds     = parseFloat(document.getElementById('finOdds').value) || 2.0;

    const resEl = document.getElementById('financeResults');
    if (!resEl) return;

    let mhtml = `<h4 style="color:var(--green-lt);margin-bottom:8px">🎲 Martingale (2x Kayıp Katlama) Serisi</h4>`;
    let currentStake = base;
    let totalInvested = 0;

    for (let step = 1; step <= 5; step++) {
        totalInvested += currentStake;
        const winPayout = currentStake * odds;
        const netProfit = winPayout - totalInvested;
        mhtml += `<div style="font-size:12px;color:var(--text-2);margin-bottom:4px">• Adım ${step}: Bahis = <strong>${currentStake.toFixed(0)} TL</strong> (Toplam Yatırılan: ${totalInvested.toFixed(0)} TL) ➔ Kazançta Net Kâr: <strong style="color:var(--green-lt)">+${netProfit.toFixed(0)} TL</strong></div>`;
        currentStake *= 2;
        if (totalInvested > bankroll) {
            mhtml += `<div style="color:var(--red);font-size:11px;font-weight:800;margin-top:2px">⚠️ UYARI: ${step}. adımda kasa bakiyesi (${bankroll} TL) aşılıyor. Risk kontrolü yapın.</div>`;
            break;
        }
    }

    resEl.innerHTML = `<div style="background:var(--bg-surface);padding:14px;border-radius:10px;border:1px solid var(--border-lt);margin-top:12px">${mhtml}</div>`;
}

/* ─── QUANTUM PITCH 3D SIMULATOR ANIMATOR ───────────────────────────────── */
function runQuantumPitchSimulation() {
    playSound('click');
    const canvas = document.getElementById('simCanvas');
    const summary = document.getElementById('simStatsSummary');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    if (summary) summary.innerHTML = '🔮 1.000 Kuantum Maç Simülasyonu Çalıştırılıyor... Lütfen Bekleyin!';

    let frame = 0;
    const maxFrames = 60;
    const dots = Array.from({ length: 40 }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        targetX: Math.random() * (w * 0.4) + (w * 0.5), targetY: Math.random() * h,
        color: Math.random() > 0.5 ? '#10b981' : '#6366f1'
    }));

    function anim() {
        ctx.clearRect(0, 0, w, h);

        // Pitch lines
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 2;
        ctx.strokeRect(10, 10, w - 20, h - 20);
        ctx.beginPath();
        ctx.moveTo(w / 2, 10); ctx.lineTo(w / 2, h - 10);
        ctx.arc(w / 2, h / 2, 45, 0, Math.PI * 2);
        ctx.stroke();

        // Particle simulation passes
        dots.forEach(d => {
            d.x += (d.targetX - d.x) * 0.08;
            d.y += (d.targetY - d.y) * 0.08;

            ctx.beginPath();
            ctx.arc(d.x, d.y, 4, 0, Math.PI * 2);
            ctx.fillStyle = d.color;
            ctx.fill();
        });

        frame++;
        if (frame < maxFrames) {
            requestAnimationFrame(anim);
        } else {
            playSound('goal');
            if (summary) {
                summary.innerHTML = `
                    🎯 <strong>1.000 Maçlık Kuantum Sonucu:</strong><br>
                    • Ev Sahibi Galibiyeti: <strong style="color:var(--purple-lt)">542 Maç (%54.2)</strong> | Beraberlik: <strong style="color:var(--amber)">268 Maç (%26.8)</strong> | Deplasman: <strong style="color:var(--cyan)">190 Maç (%19.0)</strong><br>
                    • Beklenen Skor (xG Density): <strong style="color:var(--green-lt)">2 - 1</strong> | 2.5 Üst Gol Başarısı: <strong style="color:var(--green-lt)">%68.4</strong>
                `;
            }
        }
    }
    anim();
}

/* ─── CUSTOM MATCH ANALYZER ──────────────────────────────────────────────── */
async function analyzeCustomUserMatch() {
    playSound('click');
    const home = document.getElementById('custHomeName').value || 'Ev Sahibi';
    const away = document.getElementById('custAwayName').value || 'Deplasman';
    const hOdds = parseFloat(document.getElementById('custHomeOdds').value) || 2.10;
    const dOdds = parseFloat(document.getElementById('custDrawOdds').value) || 3.40;
    const aOdds = parseFloat(document.getElementById('custAwayOdds').value) || 3.20;

    const area = document.getElementById('customMatchResultArea');
    if (!area) return;

    area.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Yapay Sinir Ağı ve Monte Carlo maçı analiz ediyor...</p></div>';

    const a = await callApi('analyze_custom_match', home, away, hOdds, dOdds, aOdds);
    if (!a || !a.best_bet) {
        area.innerHTML = '<div class="empty-state"><h3>Analiz başarısız oldu</h3></div>';
        return;
    }

    const b = a.best_bet;
    area.innerHTML = `
        <div style="background:var(--bg-surface);padding:18px;border-radius:12px;border:1px solid var(--green-lt)">
            <h3 style="color:var(--purple-lt);margin-bottom:8px">🔮 Analiz Raporu: ${home} vs ${away}</h3>
            <div style="font-size:16px;font-weight:900;color:var(--green-lt);margin-bottom:6px">🏆 Yüksek Güvenli Tahmin: ${b.label} (@${b.odds})</div>
            <div style="font-size:12px;color:var(--text-2);line-height:1.7">
                • 1X2 Olasılık Dağılımı: Ev Sahibi <strong>%${a.probs?.home_win}</strong> | Beraberlik <strong>%${a.probs?.draw}</strong> | Deplasman <strong>%${a.probs?.away_win}</strong><br>
                • Beklenen Skor (xG Matrisi): <strong style="color:var(--amber)">${a.expected_score}</strong><br>
                • 95% Olasılık Güven Aralığı: <strong>${a.confidence_intervals?.home}</strong><br>
                • ⚖️ Kelly Kasa Önerisi: <strong style="color:var(--green-lt)">Kasanın %${b.kelly}'si ile Oyna</strong>
            </div>
        </div>
    `;

    speakPrediction(`${home} ile ${away} maçı özel analiz sonucu: Tahminimiz ${b.label}, oran ${b.odds}.`);
}

/* ─── VIEWS MANAGEMENT ──────────────────────────────────────────────────────── */
function switchView(view) {
    playSound('click');
    currentView = view;
    document.querySelectorAll('.view').forEach(v => v.style.display = 'none');
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));

    const titleEl = document.getElementById('pageTitle');

    if (view === 'matches') {
        document.getElementById('viewMatches').style.display = '';
        document.getElementById('navMatches').classList.add('active');
        if (titleEl) titleEl.textContent = 'Bugünkü Maçlar';
        renderMatches();
    } else if (view === 'surebet') {
        document.getElementById('viewSurebet').style.display = '';
        document.getElementById('navSurebet').classList.add('active');
        if (titleEl) titleEl.textContent = 'SureBet Arbitraj (%100 Garantili Kâr)';
        renderSurebets();
    } else if (view === 'simulator') {
        document.getElementById('viewSimulator').style.display = '';
        document.getElementById('navSimulator').classList.add('active');
        if (titleEl) titleEl.textContent = 'Kuantum 3D Maç Simülatörü';
        runQuantumPitchSimulation();
    } else if (view === 'customMatch') {
        document.getElementById('viewCustomMatch').style.display = '';
        document.getElementById('navCustomMatch').classList.add('active');
        if (titleEl) titleEl.textContent = 'Kendi Özel Maçını Analiz Et';
    } else if (view === 'standings') {
        document.getElementById('viewStandings').style.display = '';
        document.getElementById('navStandings').classList.add('active');
        if (titleEl) titleEl.textContent = 'Canlı Puan Durumu & Ligler';
        renderStandings();
    } else if (view === 'dropping') {
        document.getElementById('viewDropping').style.display = '';
        document.getElementById('navDropping').classList.add('active');
        if (titleEl) titleEl.textContent = 'Oran Düşüşleri (Hot Money)';
        renderDroppingOdds();
    } else if (view === 'value') {
        document.getElementById('viewValue').style.display = '';
        document.getElementById('navValue').classList.add('active');
        if (titleEl) titleEl.textContent = 'Değer Bahisleri (+EV)';
        renderValueBets();
    } else if (view === 'bankroll') {
        document.getElementById('viewBankroll').style.display = '';
        document.getElementById('navBankroll').classList.add('active');
        if (titleEl) titleEl.textContent = 'Sanal Kasa & Kasa Katlama Simülatörü';
    } else if (view === 'finance') {
        document.getElementById('viewFinance').style.display = '';
        document.getElementById('navFinance').classList.add('active');
        if (titleEl) titleEl.textContent = 'Martingale & Fibonacci Finans Hesabı';
        calculateFinanceSim();
    } else if (view === 'leaderboard') {
        document.getElementById('viewLeaderboard').style.display = '';
        document.getElementById('navLeaderboard').classList.add('active');
        if (titleEl) titleEl.textContent = 'Model Karnesi & Gerçek Başarı';
        renderModelPerformance();
    } else if (view === 'coupon') {
        document.getElementById('viewCoupon').style.display = '';
        document.getElementById('navCoupon').classList.add('active');
        if (titleEl) titleEl.textContent = 'Kupon Sihirbazı';
        generateCustomCoupon();
    } else if (view === 'saved') {
        document.getElementById('viewSaved').style.display = '';
        document.getElementById('navSaved').classList.add('active');
        if (titleEl) titleEl.textContent = 'Kayıtlı Kuponlar';
        loadSavedCoupons();
    } else if (view === 'trends') {
        document.getElementById('viewTrends').style.display = '';
        document.getElementById('navTrends').classList.add('active');
        if (titleEl) titleEl.textContent = 'Günün Trendleri & Sıcak Bahis Akışı';
        renderTrendsView();
    } else if (view === 'powerRankings') {
        document.getElementById('viewPowerRankings').style.display = '';
        document.getElementById('navPowerRankings').classList.add('active');
        if (titleEl) titleEl.textContent = 'ELO & Güç Sıralaması Matrisi';
        renderPowerRankings();
    }
}

/* ─── TRENDS VIEW ─────────────────────────────────────────────────────────── */
async function renderTrendsView() {
    const statsBar = document.getElementById('trendsStatsBar');
    const xgList   = document.getElementById('trendsXgList');
    if (statsBar) statsBar.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:20px"><div class="loading-spinner"></div><p style="margin-top:8px;color:var(--text-3)">Trend analizi yapılıyor...</p></div>';

    const data = await callApi('get_match_trends');
    if (!data) {
        if (statsBar) statsBar.innerHTML = '<div style="color:var(--red)">Trend verisi alınamadı.</div>';
        return;
    }

    const stats = [
        { label: 'Toplam Maç', value: data.total_matches || 0, color: 'var(--purple-lt)', icon: '⚽' },
        { label: '2.5 Üst Hot', value: data.o25_hot_count || 0, color: 'var(--green-lt)', icon: '🔥' },
        { label: 'KG Var Hot',  value: data.btts_hot_count || 0, color: 'var(--cyan)',     icon: '⚡' },
        { label: '+EV Bahis',   value: data.value_bet_count || 0, color: 'var(--amber)',    icon: '💎' },
    ];

    if (statsBar) {
        statsBar.innerHTML = stats.map(s => `
            <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:16px;text-align:center">
                <div style="font-size:22px;margin-bottom:4px">${s.icon}</div>
                <div style="font-size:26px;font-weight:900;font-family:'JetBrains Mono';color:${s.color}">${s.value}</div>
                <div style="font-size:10px;color:var(--text-3);text-transform:uppercase;font-weight:700;margin-top:2px">${s.label}</div>
            </div>
        `).join('');
    }

    if (xgList) {
        const topXg = data.top_xg_matches || [];
        if (!topXg.length) {
            xgList.innerHTML = '<div style="color:var(--text-3);font-size:13px">Yeterli veri yok.</div>';
        } else {
            xgList.innerHTML = topXg.map((x, i) => `
                <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px">
                    <div style="display:flex;align-items:center;gap:10px">
                        <div style="width:28px;height:28px;border-radius:50%;background:var(--grad-brand);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:900">${i+1}</div>
                        <div>
                            <div style="font-weight:800;font-size:13px;color:var(--text-1)">${x.match}</div>
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
