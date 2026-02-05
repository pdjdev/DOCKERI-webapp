import type { Conversation } from '../types';
import { Plus, ChevronLeft, Menu, File, Trash, MessageCircle } from '@boxicons/react';

interface DocumentListProps {
  documents: string[];
  onDeleteClick: (filename: string) => void;
}

export function DocumentList({ documents, onDeleteClick }: DocumentListProps) {
  if (!documents || documents.length === 0) {
    return (
      <p style={{ padding: '10px', fontSize: '12px', color: '#666' }}>
        저장된 문서가 없습니다.
      </p>
    );
  }

  return (
    <>
      {documents.map((doc) => (
        <div key={doc} className="doc-item">
          <div className="doc-info">
            <File />
            <span className="doc-title">{doc}</span>
          </div>
          <button
            className="delete-btn"
            onClick={() => onDeleteClick(doc)}
            title="문서 삭제"
          >
            <Trash />
          </button>
        </div>
      ))}
    </>
  );
}

interface ConversationListProps {
  conversations: Conversation[];
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
}

export function ConversationList({
  conversations,
  onOpenConversation,
  onDeleteConversation,
}: ConversationListProps) {
  if (!conversations || conversations.length === 0) {
    return (
      <p style={{ padding: '10px', fontSize: '12px', color: '#666' }}>
        저장된 대화가 없습니다.
      </p>
    );
  }

  return (
    <>
      {conversations.map((conv) => (
        <div key={conv.id} className="doc-item" title={conv.title}>
          <div
            className="doc-info"
            onClick={() => onOpenConversation(conv.id)}
          >
            <MessageCircle />
            <span className="doc-title">{conv.title}</span>
          </div>
          <button
            className="delete-btn"
            onClick={(e) => {
              e.stopPropagation();
              onDeleteConversation(conv.id);
            }}
            title="대화 삭제"
          >
            <Trash />
          </button>
        </div>
      ))}
    </>
  );
}

interface SidebarProps {
  isClosed: boolean;
  isBackendOnline: boolean;
  documents: string[];
  conversations: Conversation[];
  onToggleSidebar: () => void;
  onNewChat: () => void;
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onDeleteDocument: (filename: string) => void;
}

export function Sidebar({
  isClosed,
  isBackendOnline,
  documents,
  conversations,
  onToggleSidebar,
  onNewChat,
  onOpenConversation,
  onDeleteConversation,
  onDeleteDocument,
}: SidebarProps) {
  return (
    <aside className={`sidebar ${isClosed ? 'closed' : ''}`} id="sidebar">
      <div className="sidebar-header">
        <button className="new-chat-btn" id="new-chat-btn" onClick={onNewChat}>
          <Plus /> 새 채팅
        </button>
        <button
          className="close-sidebar-btn"
          id="close-sidebar-btn"
          onClick={onToggleSidebar}
        >
          <ChevronLeft />
        </button>
      </div>

      <div className="recent-chats">
        <p className="recent-label">문서 목록</p>
        <div id="doc-list">
          <DocumentList
            documents={documents}
            onDeleteClick={onDeleteDocument}
          />
        </div>
      </div>

      <div className="recent-chats">
        <p className="recent-label">대화 목록</p>
        <div id="conv-list">
          <ConversationList
            conversations={conversations}
            onOpenConversation={onOpenConversation}
            onDeleteConversation={onDeleteConversation}
          />
        </div>
      </div>

      <div className="sidebar-footer">
        <div className="location-info">
          <span className={`dot ${isBackendOnline ? '' : 'offline'}`}></span>{' '}
          백엔드 연결 상태
        </div>
      </div>
    </aside>
  );
}

interface TopNavProps {
  onMenuToggle: () => void;
}

export function TopNav({ onMenuToggle }: TopNavProps) {
  return (
    <nav className="top-nav">
      <div className="nav-left">
        <button className="icon-btn" id="menu-toggle" onClick={onMenuToggle}>
          <Menu />
        </button>
        <button className="model-selector">DOCKERI Agent</button>
      </div>
      <div className="nav-right">
        <div className="user-avatar">U</div>
      </div>
    </nav>
  );
}

interface DeleteModalProps {
  isActive: boolean;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function DeleteModal({
  isActive,
  message,
  onConfirm,
  onCancel,
}: DeleteModalProps) {
  return (
    <div
      className={`modal-backdrop ${isActive ? 'active' : ''}`}
      id="delete-modal"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal-content">
        <h3 className="modal-title">문서 삭제</h3>
        <p className="modal-text" id="delete-msg">
          {message}
        </p>
        <div className="modal-actions">
          <button className="btn btn-cancel" onClick={onCancel}>
            취소
          </button>
          <button className="btn btn-danger" id="confirm-delete-btn" onClick={onConfirm}>
            삭제
          </button>
        </div>
      </div>
    </div>
  );
}
