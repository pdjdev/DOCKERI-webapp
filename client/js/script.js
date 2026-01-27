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

// 2. 메시지 추가 (Bot)
function appendBotMessage(markdownText, sources = []) {
    const div = document.createElement('div');
    div.className = 'message-row bot';
    
    // Markdown 파싱
    const htmlContent = marked.parse(markdownText);
    
    let sourceHtml = '';
    if (sources && sources.length > 0) {
        const uniqueSources = [...new Map(sources.map(item => [item.source, item])).values()];
        sourceHtml = `
            <div class="sources-container">
                <div class="sources-header" onclick="this.nextElementSibling.classList.toggle('open')">
                    <span>📚 참고 문서 (${uniqueSources.length})</span>
                    <i class='bx bx-chevron-down'></i>
                </div>
                <div class="sources-list">
                    ${uniqueSources.map(s => `
                        <div class="source-item">
                            <div class="source-filename">${s.source}</div>
                            <div style="color:#aaa;">${s.content}...</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    div.innerHTML = `
        <div class="message-avatar bot-avatar">AI</div>
        <div style="flex:1; max-width: 80%;">
            <div class="message-content">${htmlContent}</div>
            ${sourceHtml}
        </div>
    `;
    chatHistory.appendChild(div);
    scrollToBottom();
}

// 3. 로딩 표시
function showLoading() {
    const div = document.createElement('div');
    div.id = 'loading-indicator';
    div.className = 'message-row bot';
    div.innerHTML = `
        <div class="message-avatar bot-avatar">AI</div>
        <div class="loading-dots">
            <span></span><span></span><span></span>
        </div>
    `;
    chatHistory.appendChild(div);
    scrollToBottom();
    return div;
}

function hideLoading() {
    const loader = document.getElementById('loading-indicator');
    if(loader) loader.remove();
}

function scrollToBottom() {
    const container = document.getElementById('chat-container');
    container.scrollTop = container.scrollHeight;
}

// 4. API 통신
async function sendMessage() {
    const text = promptInput.value.trim();
    if (!text) return;

    // UI 업데이트
    promptInput.value = '';
    promptInput.style.height = 'auto';
    appendUserMessage(text);
    showLoading();

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: text })
        });

        if (!response.ok) throw new Error("Server Error");

        const data = await response.json();
        hideLoading();
        appendBotMessage(data.answer, data.sources);

    } catch (error) {
        hideLoading();
        appendBotMessage(`⚠️ 오류가 발생했습니다: ${error.message}`);
    }
}

// 5. 파일 업로드
fileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    appendUserMessage(`📄 파일 업로드 중: ${file.name}`);
    showLoading();

    try {
        const res = await fetch(`${API_BASE_URL}/upload`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        hideLoading();
        appendBotMessage(`✅ ${data.message || '업로드 완료'}`);
        loadDocumentList(); // 목록 갱신
    } catch (err) {
        hideLoading();
        appendBotMessage(`❌ 업로드 실패: ${err.message}`);
    }
    fileInput.value = '';
});

// 6. 문서 목록 로드 (사이드바) - 삭제 버튼 추가됨
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
        } else {
            docListContainer.innerHTML = '<p style="padding:10px; font-size:12px; color:#666;">저장된 문서가 없습니다.</p>';
        }
    } catch (e) {
        console.error("문서 목록 로드 실패", e);
    }
}

// 7. 문서 삭제 관련 로직
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
    
    // UI 피드백 (채팅창에 로그 남기기)
    appendUserMessage(`🗑️ 문서 삭제 요청: ${filename}`);
    showLoading();

    try {
        // DELETE 호출 (특수문자 포함 파일명 대응을 위해 encodeURIComponent)
        const res = await fetch(`${API_BASE_URL}/documents?filename=${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });

        if (!res.ok) throw new Error("Delete Request Failed");

        hideLoading();
        appendBotMessage(`✅ '${filename}' 삭제 완료.`);
        loadDocumentList(); // 목록 갱신

    } catch (err) {
        hideLoading();
        appendBotMessage(`❌ 삭제 실패: ${err.message}`);
    }
});

// --- Event Listeners ---
document.addEventListener('DOMContentLoaded', () => {
    loadDocumentList(); // 초기 문서 목록 로드
    
    // 추천 질문 카드 생성
    const suggestions = [
        { text: "현재 저장된 문서들의 핵심 요약해줘", color: "#60a5fa" },
        { text: "이 기술 문서에서 언급된 주요 이슈는?", color: "#fbbf24" }
    ];
    document.getElementById('suggestion-cards').innerHTML = suggestions.map(card => `
        <div class="card" onclick="document.getElementById('prompt-input').value='${card.text}'; sendMessage();">
            <p class="card-text">${card.text}</p>
            <div class="card-icon-wrapper"><i class="bx bx-bulb icon-sm" style="color: ${card.color};"></i></div>
        </div>
    `).join('');

    // 입력창 엔터 처리
    promptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // 전송 버튼
    sendBtn.addEventListener('click', sendMessage);

    // 입력창 높이 자동 조절
    promptInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
    });

    // 사이드바 토글
    document.getElementById('menu-toggle').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('closed');
    });
    
    // 새 채팅
    document.getElementById('new-chat-btn').addEventListener('click', () => {
        location.reload();
    });

    // 모달 배경 클릭 시 닫기
    deleteModal.addEventListener('click', (e) => {
        if (e.target === deleteModal) closeModal();
    });
});