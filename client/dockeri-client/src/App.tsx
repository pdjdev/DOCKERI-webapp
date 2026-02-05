import { useState, useEffect, useCallback } from 'react';
import type { Conversation, Message } from './types';
import axiosClient from './api/axiosClient';
import { saveConversations, loadConversations } from './utils/localStorage';
import { Sidebar, TopNav, DeleteModal } from './components/SidebarComponents';
import { ChatDisplay, InputArea, UploadProgress } from './components/ChatComponents';
import {
  getDocuments,
  deleteDocument,
  uploadFile,
  pollUploadStatus,
} from './services/apiService';

function App() {
  const [sidebarClosed, setSidebarClosed] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [chatContext, setChatContext] = useState<Message[]>([]);
  const [promptValue, setPromptValue] = useState('');
  const [documents, setDocuments] = useState<string[]>([]);
  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [deleteModalActive, setDeleteModalActive] = useState(false);
  const [targetFileToDelete, setTargetFileToDelete] = useState<string | null>(null);
  const [deleteModalMessage, setDeleteModalMessage] = useState('');
  const [uploadStatus, setUploadStatus] = useState<{ message: string; progress: number; status: string } | null>(null);

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
    const savedConvs = loadConversations();
    setConversations(savedConvs);
    loadDocuments();
  }, [loadDocuments]);

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

    const userMsg = { role: 'user' as const, parts: [{ text: `🗑️ 문서 삭제 요청: ${filename}` }] };
    const newContext = [...chatContext, userMsg];
    setChatContext(newContext);

    try {
      await deleteDocument(filename);

      const botMsg = { role: 'model' as const, parts: [{ text: `✅ '${filename}' 삭제 완료.` }] };
      const finalContext = [...newContext, botMsg];
      setChatContext(finalContext);

      if (currentConversationId) {
        const updatedConvs = conversations.map((c) =>
          c.id === currentConversationId ? { ...c, messages: finalContext } : c
        );
        setConversations(updatedConvs);
        saveConversations(updatedConvs);
      }

      await loadDocuments();
    } catch (err: any) {
      const botMsg = {
        role: 'model' as const,
        parts: [{ text: `❌ 삭제 실패: ${err.message}` }],
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

    if (!currentConversationId) {
      const id = Date.now().toString();
      const title = text;
      const newConv: Conversation = {
        id,
        title,
        messages: newContext,
        createdAt: id,
      };
      const newConversations = [newConv, ...conversations];
      setConversations(newConversations);
      setCurrentConversationId(id);
      saveConversations(newConversations);
    } else {
      const updatedConvs = conversations.map((c) =>
        c.id === currentConversationId ? { ...c, messages: newContext } : c
      );
      setConversations(updatedConvs);
      saveConversations(updatedConvs);
    }

    try {
      const response = await axiosClient.post('/chat', {
        contents: newContext,
      });

      let accumulatedText = response.data;

      if (typeof response.data === 'string') {
        accumulatedText = response.data;
      } else if (response.data?.text) {
        accumulatedText = response.data.text;
      }

      const botMsg = { role: 'model' as const, parts: [{ text: accumulatedText }] };
      const finalContext = [...newContext, botMsg];
      setChatContext(finalContext);

      if (currentConversationId) {
        const updatedConvs = conversations.map((c) =>
          c.id === currentConversationId ? { ...c, messages: finalContext } : c
        );
        setConversations(updatedConvs);
        saveConversations(updatedConvs);
      }
    } catch (error: any) {
      console.error(error);
      const botMsg = {
        role: 'model' as const,
        parts: [{ text: `⚠️ 오류가 발생했습니다: ${error.message}` }],
      };
      setChatContext([...newContext, botMsg]);
    }
  };

  const handleFileSelect = async (file: File) => {
    const userMsg = { role: 'user' as const, parts: [{ text: `📄 파일 업로드: ${file.name}` }] };
    const newContext = [...chatContext, userMsg];
    setChatContext(newContext);

    try {
      const data = await uploadFile(file);
      const taskId = data.task_id || data.taskId;

      if (!taskId) {
        const botMsg = { role: 'model' as const, parts: [{ text: `✅ ${data.message || '업로드 완료'}` }] };
        const finalContext = [...newContext, botMsg];
        setChatContext(finalContext);
        if (currentConversationId) {
          const updatedConvs = conversations.map((c) =>
            c.id === currentConversationId ? { ...c, messages: finalContext } : c
          );
          setConversations(updatedConvs);
          saveConversations(updatedConvs);
        }
        await loadDocuments();
        return;
      }

      cosetUploadStatus(info
        setChatContext([...newContext, progressMsg]);
      });

      if (finalStatus.status === 'done') {
        const botMsg = { role: 'model' as const, parts: [{ text: `✅ 처리 완료: ${file.name}` }] };
        const finalContext = [...newContext, botMsg];
        setChatContext(finalContext);
        setUploadStatus(null);
        if (currentConversationId) {
          const updatedConvs = conversations.map((c) =>
            c.id === currentConversationId ? { ...c, messages: finalContext } : c
          );
          setConversations(updatedConvs);
          saveConversations(updatedConvs);
        }
        await loadDocuments();
      } else {
        const botMsg = {
          role: 'model' as const,
        setUploadStatus(null);
        const botMsg = {
          role: 'model' as const,
          parts: [{ text: `❌ 처리 실패: ${finalStatus.message || '오류'}` }],
        };
        setChatContext([...newContext, botMsg]);
      }
    } catch (err: any) {
      setUploadStatus(null); const,
        parts: [{ text: `❌ 업로드 실패: ${err.message || String(err)}` }],
      };
      setChatContext([...newContext, botMsg]);
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
        {uploadStatus && <div style={{ padding: '16px' }}><UploadProgress info={uploadStatus} /></div>}

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
