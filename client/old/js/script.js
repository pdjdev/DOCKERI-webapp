// --- Configuration ---
const API_BASE_URL = window.location.origin + "/api";

// --- Elements ---
const welcomeScreen = document.getElementById('welcome-screen');
const chatHistory = document.getElementById('chat-history');
const promptInput = document.getElementById('prompt-input');
const sendBtn = document.getElementById('send-btn');
const docListContainer = document.getElementById('doc-list');
const fileInput = document.getElementById('file-upload');
const deleteModal = document.getElementById('delete-modal');
const deleteMsg = document.getElementById('delete-msg');
const confirmDeleteBtn = document.getElementById('confirm-delete-btn');

let targetFileToDelete = null;
let chatContext = []; // 대화 문맥 저장 (Multi-turn 지원)

// Local storage keys
const OLD_CHAT_KEY = 'dockeri_chat_history_v1';
const CONV_STORAGE_KEY = 'dockeri_conversations_v1';

// Conversations model
let conversations = []; // { id, title, messages: [...], createdAt }
let currentConversationId = null;

function saveConversations() {
    try {
        localStorage.setItem(CONV_STORAGE_KEY, JSON.stringify(conversations));
    } catch (e) {
        console.warn('Conversations 저장 실패', e);
    }
}

function loadConversations() {
    try {
        const raw = localStorage.getItem(CONV_STORAGE_KEY);
        if (raw) {
            const data = JSON.parse(raw);
            if (Array.isArray(data)) conversations = data;
            return;
        }

        // migration: if old single-chat key exists, migrate into conversations
        const oldRaw = localStorage.getItem(OLD_CHAT_KEY);
        if (oldRaw) {
            const msgs = JSON.parse(oldRaw);
            const id = Date.now().toString();
            const firstUser = (msgs || []).find(m => m.role === 'user');
            const title = (firstUser && firstUser.parts && firstUser.parts[0] && firstUser.parts[0].text) || ('대화 ' + new Date(id).toLocaleString());
            conversations = [{ id, title, messages: msgs, createdAt: id }];
            saveConversations();
            localStorage.removeItem(OLD_CHAT_KEY);
        }
    } catch (e) {
        console.warn('Conversations 로드 실패', e);
    }
}

function appendModelMessage(text) {
    welcomeScreen.classList.add('hidden');
    const div = document.createElement('div');
    div.className = 'message-row bot';
    div.innerHTML = `
        <div class="message-avatar bot-avatar">AI</div>
        <div class="message-content">${marked.parse(text || '')}</div>
    `;
    chatHistory.appendChild(div);
    scrollToBottom();
}

function renderChatHistory() {
    chatHistory.innerHTML = '';
    if (!chatContext || chatContext.length === 0) {
        welcomeScreen.classList.remove('hidden');
        return;
    }
    welcomeScreen.classList.add('hidden');
    for (const msg of chatContext) {
        const partsText = (msg.parts || []).map(p => p.text || '').join('\n');
        if (msg.role === 'user') {
            const div = document.createElement('div');
            div.className = 'message-row user';
            div.innerHTML = `
                <div class="message-content">${partsText}</div>
                <div class="message-avatar user-avatar-sm">U</div>
            `;
            chatHistory.appendChild(div);
        } else {
            const div = document.createElement('div');
            div.className = 'message-row bot';
            div.innerHTML = `
                <div class="message-avatar bot-avatar">AI</div>
                <div class="message-content">${marked.parse(partsText)}</div>
            `;
            chatHistory.appendChild(div);
        }
    }
    scrollToBottom();
}

function renderConversationList() {
    const container = document.getElementById('conv-list');
    if (!container) return;
    if (!conversations || conversations.length === 0) {
        container.innerHTML = '<p style="padding:10px; font-size:12px; color:#666;">저장된 대화가 없습니다.</p>';
        return;
    }

    container.innerHTML = conversations.map(conv => `
        <div class="doc-item" title="${conv.title}">
            <div class="doc-info" onclick="window.openConversation('${conv.id}')">
                <i class="bx bx-chat" style="color: #9CA3AF;"></i>
                <span class="doc-title">${conv.title}</span>
            </div>
            <button class="delete-btn" onclick="event.stopPropagation(); window.deleteConversation('${conv.id}')" title="대화 삭제">
                <i class='bx bx-trash'></i>
            </button>
        </div>
    `).join('');
}

window.openConversation = function(id) {
    const conv = conversations.find(c => c.id === id);
    if (!conv) return;
    currentConversationId = id;
    chatContext = JSON.parse(JSON.stringify(conv.messages || []));
    renderChatHistory();
};

window.deleteConversation = function(id) {
    const idx = conversations.findIndex(c => c.id === id);
    if (idx === -1) return;
    conversations.splice(idx, 1);
    if (currentConversationId === id) {
        currentConversationId = null;
        chatContext = [];
        renderChatHistory();
    }
    saveConversations();
    renderConversationList();
};

function startNewConversation() {
    currentConversationId = null;
    chatContext = [];
    // show welcome screen and reset UI
    renderChatHistory();
    welcomeScreen.classList.remove('hidden');
    const container = document.getElementById('chat-container');
    if (container) container.scrollTop = 0;
    const el = document.getElementById('prompt-input');
    if (el) el.focus();
}

// --- Functions ---

// 1. 메시지 추가 (User)
function appendUserMessage(text) {
    welcomeScreen.classList.add('hidden'); // 첫 메시지 시 웰컴 스크린 숨김
    
    const div = document.createElement('div');
    div.className = 'message-row user';
    div.innerHTML = `
        <div class="message-content">${text}</div>
        <div class="message-avatar user-avatar-sm">U</div>
    `;
    chatHistory.appendChild(div);
    scrollToBottom();
}

// 2. 봇 메시지 컨테이너 생성 (Streaming용)
function createBotMessageContainer() {
    const div = document.createElement('div');
    div.className = 'message-row bot';
    
    div.innerHTML = `
        <div class="message-avatar bot-avatar">AI</div>
        <div style="flex:1; max-width: 80%;">
            <div class="message-content">
                <div class="loading-dots">
                    <span></span><span></span><span></span>
                </div>
            </div>
        </div>
    `;
    chatHistory.appendChild(div);
    scrollToBottom();
    
    // 나중에 텍스트를 업데이트할 대상(content) 요소를 반환
    return div.querySelector('.message-content');
}

// 3. 단순 메시지 출력 (알림/에러용)
function appendSystemMessage(text, type = 'info') {
    const div = document.createElement('div');
    div.className = 'message-row bot';
    const color = type === 'error' ? 'red' : '#333';
    div.innerHTML = `
        <div class="message-avatar bot-avatar">AI</div>
        <div class="message-content" style="color:${color};">${text}</div>
    `;
    chatHistory.appendChild(div);
    scrollToBottom();
}

function scrollToBottom() {
    const container = document.getElementById('chat-container');
    container.scrollTop = container.scrollHeight;
}

// 4. API 통신 (Streaming & History)
async function sendMessage() {
    const text = promptInput.value.trim();
    if (!text) return;

    // UI 업데이트
    promptInput.value = '';
    promptInput.style.height = 'auto';
    
    // 사용자 메시지 표시
    appendUserMessage(text);
    
    // 컨텍스트에 사용자 메시지 추가
    const userMsg = { role: "user", parts: [{ text: text }] };
    chatContext.push(userMsg);

    // 새 대화인 경우(최초 메시지) 새 세션 생성
    if (!currentConversationId) {
        const id = Date.now().toString();
        const title = text;
        const conv = { id, title, messages: JSON.parse(JSON.stringify(chatContext)), createdAt: id };
        conversations.unshift(conv);
        currentConversationId = id;
        saveConversations();
        renderConversationList();
    } else {
        // 기존 대화에 메시지 동기화
        const conv = conversations.find(c => c.id === currentConversationId);
        if (conv) {
            conv.messages = JSON.parse(JSON.stringify(chatContext));
            saveConversations();
            renderConversationList();
        }
    }

    // 봇 메시지 컨테이너 생성 (로딩 상태)
    const botContentElement = createBotMessageContainer();

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                contents: chatContext,
                temperature: 0.1
            })
        });

        if (!response.ok) throw new Error("Server Error");
        if (!response.body) throw new Error("ReadableStream not supported");

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let accumulatedText = "";
        let isFirstChunk = true;

        // 스트림 읽기 루프
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            accumulatedText += chunk;

            // 첫 데이터 수신 시 로딩 애니메이션 제거
            if (isFirstChunk) {
                isFirstChunk = false;
            }

            // 마크다운 렌더링 후 업데이트
            // (marked 라이브러리가 window 객체에 있다고 가정)
            botContentElement.innerHTML = marked.parse(accumulatedText);
            
            scrollToBottom();
        }

        // 대화 완료 후 컨텍스트에 모델 응답 추가
        const modelMsg = { role: "model", parts: [{ text: accumulatedText }] };
        chatContext.push(modelMsg);
        if (currentConversationId) {
            const conv = conversations.find(c => c.id === currentConversationId);
            if (conv) {
                conv.messages = JSON.parse(JSON.stringify(chatContext));
                saveConversations();
                renderConversationList();
            }
        }

    } catch (error) {
        console.error(error);
        botContentElement.innerHTML = `<span style="color:red;">⚠️ 오류가 발생했습니다: ${error.message}</span>`;
    }
}

// 5. 파일 업로드 + 백그라운드 처리 폴링
// 저장: 업로드 직후 task_id 반환받아 폴링 시작
async function pollUploadStatus(taskId, onUpdate) {
    let interval = 2000; // 시작 2s
    const maxInterval = 5000; // 5s cap
    const start = Date.now();
    const maxTimeout = 1000 * 60 * 20; // 20분
    let consecutiveFailures = 0;

    while (true) {
        try {
            const res = await fetch(`${API_BASE_URL}/upload/status/${encodeURIComponent(taskId)}`);
            if (res.status === 404) {
                onUpdate({ status: 'failed', message: '작업을 찾을 수 없습니다', progress: 0 });
                return { status: 'failed' };
            }
            const info = await res.json();
            consecutiveFailures = 0;
            onUpdate(info);

            if (info.status === 'done' || info.status === 'failed') return info;

            if (Date.now() - start > maxTimeout) {
                onUpdate({ status: 'failed', message: '타임아웃', progress: info.progress || 0 });
                throw new Error('Polling timeout');
            }

            await new Promise(r => setTimeout(r, interval));
            interval = Math.min(interval * 2, maxInterval);

        } catch (err) {
            consecutiveFailures += 1;
            if (consecutiveFailures >= 5) {
                onUpdate({ status: 'failed', message: '네트워크 오류로 폴링 중단', progress: 0 });
                throw err;
            }
            await new Promise(r => setTimeout(r, Math.min(interval, maxInterval)));
            interval = Math.min(interval * 2, maxInterval);
        }
    }
}

function renderUploadProgressElement(el, info) {
    const progress = typeof info.progress === 'number' ? info.progress : 0;
    const safeMsg = info.message || '';
    el.innerHTML = `
        <div>
            <div style="font-weight:600; margin-bottom:8px;">${escapeHtml(safeMsg)}</div>
            <div style="background:#222; border-radius:8px; height:10px; overflow:hidden;">
                <div style="width:${progress}%; height:100%; background:#60a5fa;"></div>
            </div>
            <div style="font-size:12px; color:#9CA3AF; margin-top:8px;">상태: ${info.status || 'processing'} — ${progress}%</div>
        </div>
    `;
}

function escapeHtml(str) {
    return String(str).replace(/[&<>"]+/g, function (s) {
        return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[s];
    });
}

// persist upload task list (간단 저장)
function saveUploadTaskRecord(record) {
    try {
        const key = 'dockeri_upload_tasks_v1';
        const raw = localStorage.getItem(key);
        const arr = raw ? JSON.parse(raw) : [];
        arr.push(record);
        localStorage.setItem(key, JSON.stringify(arr));
    } catch (e) {
        console.warn('upload task 저장 실패', e);
    }
}

fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    appendUserMessage(`📄 파일 업로드: ${file.name}`);
    const loadingEl = createBotMessageContainer();

    try {
        const res = await fetch(`${API_BASE_URL}/upload`, {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const errText = await res.text();
            loadingEl.innerHTML = `<span style="color:red;">❌ 업로드 실패: ${escapeHtml(errText || res.statusText)}</span>`;
            fileInput.value = '';
            return;
        }

        const data = await res.json();
        const taskId = data.task_id || data.taskId || null;

        if (!taskId) {
            loadingEl.innerHTML = marked.parse(`✅ ${data.message || '업로드 완료'}`);
            loadDocumentList();
            fileInput.value = '';
            return;
        }

        // 저장 및 폴링 시작
        saveUploadTaskRecord({ task_id: taskId, filename: file.name, created_at: new Date().toISOString() });
        // appendUserMessage(`🔔 처리 시작: task=${taskId}`);

        // 초기 표시
        renderUploadProgressElement(loadingEl, { status: 'uploaded', message: data.message || '업로드 완료. 처리 대기 중', filename: file.name, progress: 0 });

        // 폴링
        try {
            await pollUploadStatus(taskId, (info) => {
                renderUploadProgressElement(loadingEl, info);
            });

            // 최종 상태 재조회하여 메시지 정리
            const finalRes = await fetch(`${API_BASE_URL}/upload/status/${encodeURIComponent(taskId)}`);
            if (finalRes.ok) {
                const finalInfo = await finalRes.json();
                if (finalInfo.status === 'done') {
                    loadingEl.innerHTML = marked.parse(`✅ 처리 완료: ${file.name}`);
                    loadDocumentList();
                } else {
                    loadingEl.innerHTML = `<span style="color:red;">❌ 처리 실패: ${escapeHtml(finalInfo.message || '오류')}</span>`;
                }
            }

        } catch (pollErr) {
            loadingEl.innerHTML = `<span style="color:red;">❌ 처리 중 오류: ${escapeHtml(pollErr.message || String(pollErr))}</span>`;
        }

    } catch (err) {
        loadingEl.innerHTML = `<span style="color:red;">❌ 업로드 실패: ${escapeHtml(err.message || String(err))}</span>`;
    }
    fileInput.value = '';
});

// 6. 문서 목록 로드
async function loadDocumentList() {
    try {
        const res = await fetch(`${API_BASE_URL}/documents`);
        const data = await res.json();
        
        if (data.documents && data.documents.length > 0) {
            docListContainer.innerHTML = data.documents.map(doc => `
                <div class="doc-item">
                    <div class="doc-info">
                        <i class="bx bx-file" style="color: #9CA3AF;"></i>
                        <span class="doc-title">${doc}</span>
                    </div>
                    <button class="delete-btn" onclick="openDeleteModal('${doc}')" title="문서 삭제">
                        <i class='bx bx-trash'></i>
                    </button>
                </div>
            `).join('');

            document.getElementById('connection_status').classList.remove('offline');
        } else {
            docListContainer.innerHTML = '<p style="padding:10px; font-size:12px; color:#666;">저장된 문서가 없습니다.</p>';
        }
    } catch (e) {
        console.error("문서 목록 로드 실패", e);
    }
}

// 7. 문서 삭제 관련
window.openDeleteModal = function(filename) {
    targetFileToDelete = filename;
    deleteMsg.textContent = `'${filename}' 문서를 삭제하시겠습니까?`;
    deleteModal.classList.add('active');
};

window.closeModal = function() {
    deleteModal.classList.remove('active');
    targetFileToDelete = null;
};

confirmDeleteBtn.addEventListener('click', async () => {
    if (!targetFileToDelete) return;
    
    const filename = targetFileToDelete;
    closeModal();
    
    appendUserMessage(`🗑️ 문서 삭제 요청: ${filename}`);
    const feedbackEl = createBotMessageContainer();

    try {
        const res = await fetch(`${API_BASE_URL}/documents?filename=${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });

        if (!res.ok) throw new Error("Delete Request Failed");

        feedbackEl.innerHTML = `✅ '${filename}' 삭제 완료.`;
        loadDocumentList(); 

    } catch (err) {
        feedbackEl.innerHTML = `<span style="color:red;">❌ 삭제 실패: ${err.message}</span>`;
    }
});

// --- Event Listeners ---
document.addEventListener('DOMContentLoaded', () => {
    loadConversations();
    renderConversationList();
    loadDocumentList();
    
    // 추천 질문
    const suggestions = [
        { text: "현재 저장된 문서들의 핵심 요약해줘", color: "#60a5fa" },
        { text: "이 기술 문서에서 언급된 주요 이슈는?", color: "#fbbf24" }
    ];
    document.getElementById('suggestion-cards').innerHTML = suggestions.map(card => `
        <div class="card" onclick="document.getElementById('prompt-input').value='${card.text}'; sendMessage();">
            <p class="card-text">${card.text}</p>
            <div class="card-icon-wrapper"><i class="bx bx-light-bulb icon-sm" style="color: ${card.color};"></i></div>
        </div>
    `).join('');

    // 키보드 이벤트
    promptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    promptInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });

    document.getElementById('menu-toggle').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('closed');
    });

    document.getElementById('close-sidebar-btn').addEventListener('click', () => {
        document.getElementById('sidebar').classList.add('closed');
    });
    
    // 새 채팅 (새 세션 시작)
    document.getElementById('new-chat-btn').addEventListener('click', (e) => {
        e.preventDefault();
        startNewConversation();
    });

    deleteModal.addEventListener('click', (e) => {
        if (e.target === deleteModal) closeModal();
    });
});