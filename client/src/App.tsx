import { useState, useEffect, useCallback } from 'react';
import type { Conversation, Message } from './types';
import { saveConversations, loadConversations } from './utils/localStorage';
import { Sidebar, TopNav, DeleteModal } from './components/SidebarComponents';
import { ChatDisplay, InputArea } from './components/ChatComponents';
import {
  getDocuments,
  deleteDocument,
  uploadFile,
  pollUploadStatus,
  streamChatMessage,
} from './services/apiService';

// 에러 객체 타입 가드
function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return String(error);
}

function App() {
  const [sidebarClosed, setSidebarClosed] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>(() => loadConversations());
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [chatContext, setChatContext] = useState<Message[]>([]);
  const [promptValue, setPromptValue] = useState('');
  const [documents, setDocuments] = useState<string[]>([]);
  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [deleteModalActive, setDeleteModalActive] = useState(false);
  const [targetFileToDelete, setTargetFileToDelete] = useState<string | null>(null);
  const [deleteModalMessage, setDeleteModalMessage] = useState('');
  const [isFileUploading, setIsFileUploading] = useState(false);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await getDocuments();
      if (data.documents && data.documents.length > 0) {
        setDocuments(data.documents);        
      } else {
        setDocuments([]);
      }
      setIsBackendOnline(true);
    } catch (e) {
      console.error('문서 목록 로드 실패', e);
      setIsBackendOnline(false);
    }
  }, []);

  useEffect(() => {
    const initializeDocuments = async () => {
      try {
        const data = await getDocuments();
        if (data.documents && data.documents.length > 0) {
          setDocuments(data.documents);        
        } else {
          setDocuments([]);
        }
        setIsBackendOnline(true);
      } catch (e) {
        console.error('문서 목록 로드 실패', e);
        setIsBackendOnline(false);
      }
    };
    
    initializeDocuments();
  }, []);

  // 파일 업로드 중 페이지 나가기 방지
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isFileUploading) {
        e.preventDefault();
        e.returnValue = '파일 업로드가 진행 중입니다. 정말 나가시겠습니까?';
        return e.returnValue;
      }
    };

    if (isFileUploading) {
      window.addEventListener('beforeunload', handleBeforeUnload);
    }

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [isFileUploading]);

  const handleNewChat = () => {
    setCurrentConversationId(null);
    setChatContext([]);
    setPromptValue('');
  };

  const handleOpenConversation = (id: string) => {
    const conv = conversations.find((c) => c.id === id);
    if (conv) {
      setCurrentConversationId(id);
      setChatContext(JSON.parse(JSON.stringify(conv.messages || [])));
    }
  };

  const handleDeleteConversation = (id: string) => {
    const idx = conversations.findIndex((c) => c.id === id);
    if (idx === -1) return;

    const newConversations = conversations.filter((c) => c.id !== id);
    setConversations(newConversations);
    saveConversations(newConversations);

    if (currentConversationId === id) {
      setCurrentConversationId(null);
      setChatContext([]);
    }
  };

  const openDeleteModal = (filename: string) => {
    setTargetFileToDelete(filename);
    setDeleteModalMessage(`'${filename}' 문서를 삭제하시겠습니까?`);
    setDeleteModalActive(true);
  };

  const closeDeleteModal = () => {
    setDeleteModalActive(false);
    setTargetFileToDelete(null);
  };

  const handleConfirmDelete = async () => {
    if (!targetFileToDelete) return;

    const filename = targetFileToDelete;
    closeDeleteModal();

    // 현재 대화 중이라면 빈 화면으로 전환
    if (chatContext.length > 0) {
      handleNewChat();
    }

    const userMsg = { role: 'user' as const, parts: [{ text: `문서 삭제 요청: ${filename}` }] };
    const newContext = [userMsg];
    setChatContext(newContext);

    try {
      await deleteDocument(filename);

      const botMsg = { role: 'model' as const, parts: [{ text: `'${filename}' 삭제 완료.`, icon: 'success' as const }] };
      const finalContext = [...newContext, botMsg];
      setChatContext(finalContext);

      // 더 이상 저장하지 않음 (임시 메시지이므로)

      await loadDocuments();
    } catch (err: unknown) {
      const botMsg = {
        role: 'model' as const,
        parts: [{ text: `삭제 실패: ${getErrorMessage(err)}`, icon: 'error' as const }],
      };
      setChatContext([...newContext, botMsg]);
    }
  };

  const handleSendMessage = async () => {
    const text = promptValue.trim();
    if (!text) return;

    setPromptValue('');

    const userMsg = { role: 'user' as const, parts: [{ text }] };
    const newContext = [...chatContext, userMsg];
    setChatContext(newContext);

    // 로딩 메시지 추가
    const loadingMsg = { role: 'model' as const, parts: [{ text: '' }] };
    setChatContext([...newContext, loadingMsg]);

    let convId = currentConversationId;
    let updatedConversations = conversations;

    if (!convId) {
      const id = Date.now().toString();
      const title = text;
      const newConv: Conversation = {
        id,
        title,
        messages: newContext,
        createdAt: id,
      };
      updatedConversations = [newConv, ...conversations];
      convId = id;
      setConversations(updatedConversations);
      setCurrentConversationId(id);
      saveConversations(updatedConversations);
    } else {
      const updatedConvs = conversations.map((c) =>
        c.id === convId ? { ...c, messages: newContext } : c
      );
      updatedConversations = updatedConvs;
      setConversations(updatedConvs);
      saveConversations(updatedConvs);
    }

    try {
      let accumulatedText = '';

      await streamChatMessage(newContext, (chunk) => {
        accumulatedText = chunk;
        const botMsg = { role: 'model' as const, parts: [{ text: accumulatedText }] };
        const tempContext = [...newContext, botMsg];
        setChatContext(tempContext);
      });

      // 최종 저장 (convId를 직접 사용)
      const botMsg = { role: 'model' as const, parts: [{ text: accumulatedText }] };
      const finalContext = [...newContext, botMsg];
      setChatContext(finalContext);

      const finalConvs = updatedConversations.map((c) =>
        c.id === convId ? { ...c, messages: finalContext } : c
      );
      setConversations(finalConvs);
      saveConversations(finalConvs);
    } catch (error: unknown) {
      console.error(error);
      const botMsg = {
        role: 'model' as const,
        parts: [{ text: `오류가 발생했습니다: ${getErrorMessage(error)}`, icon: 'error' as const }],
      };
      const errorContext = [...newContext, botMsg];
      setChatContext(errorContext);
      
      const errorConvs = updatedConversations.map((c) =>
        c.id === convId ? { ...c, messages: errorContext } : c
      );
      setConversations(errorConvs);
      saveConversations(errorConvs);
    }
  };

  const handleFileSelect = async (file: File) => {
    // 현재 대화 중이라면 빈 화면으로 전환
    if (chatContext.length > 0) {
      handleNewChat();
    }

    setIsFileUploading(true);
    
    const userMsg = { role: 'user' as const, parts: [{ text: `파일 업로드: ${file.name}` }] };
    const newContext = [userMsg];
    setChatContext(newContext);

    try {
      const data = await uploadFile(file);
      const taskId = data.task_id || data.taskId;

      if (!taskId) {
        const botMsg = { role: 'model' as const, parts: [{ text: `${data.message || '업로드 완료'}`, icon: 'success' as const }] };
        const finalContext = [...newContext, botMsg];
        setChatContext(finalContext);
        // 더 이상 저장하지 않음 (임시 메시지이므로)
        await loadDocuments();
        setIsFileUploading(false);
        return;
      }

      // 진행 상황 메시지를 위한 변수
      let progressContext = [...newContext];

      const finalStatus = await pollUploadStatus(taskId, (info) => {
        const progressMsg = {
          role: 'model' as const,
          parts: [{ text: '' }],
          uploadStatus: info,
        };
        progressContext = [...newContext, progressMsg];
        setChatContext(progressContext);
      });

      if (finalStatus.status === 'done') {
        const botMsg = { role: 'model' as const, parts: [{ text: `처리 완료: ${file.name}`, icon: 'success' as const }] };
        const finalContext = [...newContext, botMsg];
        setChatContext(finalContext);
        // 더 이상 저장하지 않음 (임시 메시지이므로)
        await loadDocuments();
      } else {
        const botMsg = {
          role: 'model' as const,
          parts: [{ text: `처리 실패: ${finalStatus.message || '오류'}`, icon: 'error' as const }],
        };
        setChatContext([...newContext, botMsg]);
      }
      
      setIsFileUploading(false);
    } catch (err: unknown) {
      const botMsg = {
        role: 'model' as const,
        parts: [{ text: `업로드 실패: ${getErrorMessage(err)}`, icon: 'error' as const }],
      };
      setChatContext([...newContext, botMsg]);
      setIsFileUploading(false);
    }
  };

  const isWelcomeVisible = chatContext.length === 0;

  return (
    <div className="app-container">
      <Sidebar
        isClosed={sidebarClosed}
        isBackendOnline={isBackendOnline}
        documents={documents}
        conversations={conversations}
        onToggleSidebar={() => setSidebarClosed(!sidebarClosed)}
        onNewChat={handleNewChat}
        onOpenConversation={handleOpenConversation}
        onDeleteConversation={handleDeleteConversation}
        onDeleteDocument={openDeleteModal}
      />

      <main className="main-content">
        <TopNav onMenuToggle={() => setSidebarClosed(!sidebarClosed)} />

        <ChatDisplay
          messages={chatContext}
          isWelcomeVisible={isWelcomeVisible}
          onCardClick={(text) => {
            setPromptValue(text);
          }}
        />

        <InputArea
          promptValue={promptValue}
          onPromptChange={setPromptValue}
          onSendMessage={handleSendMessage}
          onFileSelect={handleFileSelect}
        />
      </main>

      <DeleteModal
        isActive={deleteModalActive}
        message={deleteModalMessage}
        onConfirm={handleConfirmDelete}
        onCancel={closeDeleteModal}
      />
    </div>
  );
}

export default App;
