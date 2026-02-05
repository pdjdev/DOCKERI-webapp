import { useRef, useEffect } from 'react';
import { marked } from 'marked';
import type { Message, UploadStatusInfo } from '../types';
import { escapeHtml, scrollToBottom } from '../utils/helpers';
import { Plus, Send, LightBulb } from '@boxicons/react';

interface MessageRowProps {
  message: Message;
}

export function MessageRow({ message }: MessageRowProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const partsText = (message.parts || []).map((p) => p.text || '').join('\n');

  // sources 토글 기능 추가 및 파일명 강조
  useEffect(() => {
    const handleClick = (e: Event) => {
      const target = e.target as HTMLElement;
      if (target.classList.contains('sources-title')) {
        const sourcesDiv = target.closest('.sources');
        if (sourcesDiv) {
          const list = sourcesDiv.querySelector('ul');
          if (list) {
            list.classList.toggle('open');
          }
        }
      }
    };

    const container = contentRef.current;
    if (container) {
      // 클릭 핸들러 추가
      container.addEventListener('click', handleClick);

      // 모든 sources 섹션에 대해 처리 (sources-title 클릭 가능하도록)
      const sourcesTitles = container.querySelectorAll('.sources-title');
      sourcesTitles.forEach((title) => {
        title.style.cursor = 'pointer';
      });

      // 각 sources 섹션 내의 li 항목들 포맷팅
      const sourceItems = container.querySelectorAll('.sources li');
      sourceItems.forEach((li) => {
        const text = li.textContent || '';
        // 파일명 추출 (예: "filename.pdf:" 형식)
        const fileMatch = text.match(/^([^:]+\.(?:pdf|md|txt|doc|docx)):\s*/i);
        
        if (fileMatch) {
          const filename = fileMatch[1];
          const description = text.substring(fileMatch[0].length);
          
          // 내용 재구성
          li.innerHTML = '';
          const filenameEl = document.createElement('strong');
          filenameEl.textContent = filename;
          li.appendChild(filenameEl);
          
          if (description.trim()) {
            const descEl = document.createElement('div');
            descEl.style.marginTop = '4px';
            descEl.style.color = '#9CA3AF';
            descEl.style.fontSize = '12px';
            descEl.style.lineHeight = '1.4';
            descEl.textContent = description;
            li.appendChild(descEl);
          }
        }
      });

      return () => {
        container.removeEventListener('click', handleClick);
      };
    }
  }, [partsText]);

  if (message.role === 'user') {
    return (
      <div className="message-row user">
        <div className="message-content">{partsText}</div>
        <div className="message-avatar user-avatar-sm">U</div>
      </div>
    );
  }

  // 업로드 진행 상황이 있으면 UploadProgress 표시
  if (message.uploadStatus) {
    return (
      <div className="message-row bot">
        <div className="message-avatar bot-avatar">AI</div>
        <div style={{ flex: 1, maxWidth: '80%' }}>
          <UploadProgress info={message.uploadStatus} />
        </div>
      </div>
    );
  }

  // 로딩 상태 (빈 text일 때)
  if (partsText === '') {
    return (
      <div className="message-row bot">
        <div className="message-avatar bot-avatar">AI</div>
        <div style={{ flex: 1, maxWidth: '80%' }}>
          <div className="message-content">
            <div className="loading-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="message-row bot">
      <div className="message-avatar bot-avatar">AI</div>
      <div
        ref={contentRef}
        className="message-content"
        dangerouslySetInnerHTML={{ __html: marked.parse(partsText) }}
      />
    </div>
  );
}

interface BotMessageContainerProps {
  contentRef: React.RefObject<HTMLDivElement>;
}

export function BotMessageContainer({ contentRef }: BotMessageContainerProps) {
  return (
    <div className="message-row bot">
      <div className="message-avatar bot-avatar">AI</div>
      <div style={{ flex: 1, maxWidth: '80%' }}>
        <div ref={contentRef} className="message-content">
          <div className="loading-dots">
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </div>
    </div>
  );
}

interface ChatDisplayProps {
  messages: Message[];
  isWelcomeVisible: boolean;
  onCardClick: (text: string) => void;
}

export function ChatDisplay({
  messages,
  isWelcomeVisible,
  onCardClick,
}: ChatDisplayProps) {
  const chatAreaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollToBottom(chatAreaRef.current);
  }, [messages]);

  const suggestions = [
    { text: '현재 저장된 문서들의 핵심 요약해줘', color: '#60a5fa' },
    { text: '이 기술 문서에서 언급된 주요 이슈는?', color: '#fbbf24' },
  ];

  return (
    <section className="chat-area" ref={chatAreaRef} id="chat-container">
      {isWelcomeVisible && (
        <div className="welcome-container" id="welcome-screen">
          <h1 className="welcome-title">
            <span className="gradient-text">안녕하세요,</span>
          </h1>
          <h2 className="welcome-subtitle">무엇을 도와드릴까요?</h2>
          <div className="cards-grid" id="suggestion-cards">
            {suggestions.map((card, idx) => (
              <div
                key={idx}
                className="card"
                onClick={() => onCardClick(card.text)}
              >
                <p className="card-text">{card.text}</p>
                <div className="card-icon-wrapper">
                  <LightBulb style={{ color: card.color }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div id="chat-history">
        {messages.map((msg, idx) => (
          <MessageRow key={idx} message={msg} />
        ))}
      </div>
    </section>
  );
}

interface InputAreaProps {
  promptValue: string;
  onPromptChange: (value: string) => void;
  onSendMessage: () => void;
  onFileSelect: (file: File) => void;
}

export function InputArea({
  promptValue,
  onPromptChange,
  onSendMessage,
  onFileSelect,
}: InputAreaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onPromptChange(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSendMessage();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileSelect(file);
      e.target.value = '';
    }
  };

  return (
    <div className="input-wrapper">
      <div className="input-container-center">
        <div className="input-box">
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.md,.txt"
            style={{ display: 'none' }}
            onChange={handleFileChange}
            id="file-upload"
          />
          <button
            className="icon-btn"
            onClick={() => fileInputRef.current?.click()}
            title="문서 업로드"
          >
            <Plus />
          </button>

          <textarea
            ref={textareaRef}
            rows={1}
            placeholder="질문을 입력하세요..."
            value={promptValue}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
          />

          <button className="icon-btn" id="send-btn" onClick={onSendMessage}>
            <Send />
          </button>
        </div>
        <p className="disclaimer">
          DOCKERI는 부정확한 정보를 표시할 수 있습니다. 문서를 기반으로 답변합니다.
        </p>
      </div>
    </div>
  );
}

interface UploadProgressProps {
  info: UploadStatusInfo;
}

export function UploadProgress({ info }: UploadProgressProps) {
  const progress = typeof info.progress === 'number' ? info.progress : 0;
  const safeMsg = info.message || '';

  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {escapeHtml(safeMsg)}
      </div>
      <div style={{ background: '#222', borderRadius: 8, height: 10, overflow: 'hidden' }}>
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            background: '#60a5fa',
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: '#9CA3AF', marginTop: 8 }}>
        상태: {info.status || 'processing'} — {progress}%
      </div>
    </div>
  );
}
