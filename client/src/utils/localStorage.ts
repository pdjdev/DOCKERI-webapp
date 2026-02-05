import type { Conversation } from '../types';

const CONV_STORAGE_KEY = 'dockeri_conversations_v1';
const OLD_CHAT_KEY = 'dockeri_chat_history_v1';

export function saveConversations(conversations: Conversation[]) {
  try {
    localStorage.setItem(CONV_STORAGE_KEY, JSON.stringify(conversations));
  } catch (e) {
    console.warn('Conversations 저장 실패', e);
  }
}

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONV_STORAGE_KEY);
    if (raw) {
      const data = JSON.parse(raw);
      if (Array.isArray(data)) return data;
    }

    // migration: old single-chat key
    const oldRaw = localStorage.getItem(OLD_CHAT_KEY);
    if (oldRaw) {
      const msgs = JSON.parse(oldRaw);
      const id = Date.now().toString();
      const firstUser = (msgs || []).find((m: any) => m.role === 'user');
      const title =
        (firstUser && firstUser.parts && firstUser.parts[0] && firstUser.parts[0].text) ||
        '대화 ' + new Date(parseInt(id)).toLocaleString();
      const conversations = [{ id, title, messages: msgs, createdAt: id }];
      saveConversations(conversations);
      localStorage.removeItem(OLD_CHAT_KEY);
      return conversations;
    }
  } catch (e) {
    console.warn('Conversations 로드 실패', e);
  }
  return [];
}
