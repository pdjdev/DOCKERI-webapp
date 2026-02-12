import Dexie, { type Table } from 'dexie';
import type { Conversation } from '../types';

// IndexedDB 스키마 정의
interface ConversationDB extends Conversation {
  id: string; // primary key
}

// Dexie 데이터베이스 클래스
class ConversationDatabase extends Dexie {
  conversations!: Table<ConversationDB>;

  constructor() {
    super('DOCKERI_ConversationsDB');
    
    // 버전 1: 기본 스키마
    this.version(1).stores({
      conversations: 'id, title, createdAt' // id가 primary key, title과 createdAt는 인덱스
    });
  }
}

// 데이터베이스 인스턴스
const db = new ConversationDatabase();

// localStorage 키 (마이그레이션용)
const CONV_STORAGE_KEY = 'dockeri_conversations_v1';
const OLD_CHAT_KEY = 'dockeri_chat_history_v1';
const MIGRATION_DONE_KEY = 'dockeri_indexeddb_migration_done';

/**
 * localStorage에서 IndexedDB로 데이터 마이그레이션
 */
async function migrateFromLocalStorage(): Promise<void> {
  // 이미 마이그레이션 완료했으면 스킵
  if (localStorage.getItem(MIGRATION_DONE_KEY)) {
    return;
  }

  try {
    console.log('localStorage에서 IndexedDB로 데이터 마이그레이션 시작...');
    
    // 기존 대화 데이터 가져오기
    const existingConversations = await loadConversationsFromLocalStorage();
    
    if (existingConversations.length > 0) {
      // IndexedDB에 저장
      await db.conversations.bulkAdd(existingConversations);
      console.log(`${existingConversations.length}개의 대화를 IndexedDB로 마이그레이션 완료`);
    }

    // 마이그레이션 완료 표시
    localStorage.setItem(MIGRATION_DONE_KEY, 'true');
    
    // 기존 localStorage 데이터 제거 (선택사항 - 백업으로 남길 수도 있음)
    // localStorage.removeItem(CONV_STORAGE_KEY);
    // localStorage.removeItem(OLD_CHAT_KEY);
    
  } catch (error) {
    console.error('마이그레이션 실패:', error);
    // 마이그레이션 실패해도 앱은 계속 작동하도록 함
  }
}

/**
 * localStorage에서 대화 데이터 로드 (마이그레이션용)
 */
function loadConversationsFromLocalStorage(): Conversation[] {
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
      return [{ id, title, messages: msgs, createdAt: id }];
    }
  } catch (e) {
    console.warn('localStorage 데이터 로드 실패:', e);
  }
  return [];
}

/**
 * 대화 목록 저장 (IndexedDB)
 */
export async function saveConversations(conversations: Conversation[]): Promise<void> {
  try {
    // 마이그레이션 확인
    await migrateFromLocalStorage();
    
    // 모든 기존 대화 삭제 후 새로 저장
    await db.conversations.clear();
    await db.conversations.bulkAdd(conversations);
  } catch (error) {
    console.error('Conversations 저장 실패:', error);
    throw error;
  }
}

/**
 * 대화 목록 로드 (IndexedDB)
 */
export async function loadConversations(): Promise<Conversation[]> {
  try {
    // 마이그레이션 확인
    await migrateFromLocalStorage();
    
    // createdAt 기준으로 정렬해서 반환
    const conversations = await db.conversations
      .orderBy('createdAt')
      .reverse() // 최신 순
      .toArray();
    
    return conversations;
  } catch (error) {
    console.error('Conversations 로드 실패:', error);
    return [];
  }
}

/**
 * 단일 대화 저장
 */
export async function saveConversation(conversation: Conversation): Promise<void> {
  try {
    await db.conversations.put(conversation);
  } catch (error) {
    console.error('Conversation 저장 실패:', error);
    throw error;
  }
}

/**
 * 단일 대화 로드
 */
export async function loadConversation(id: string): Promise<Conversation | undefined> {
  try {
    return await db.conversations.get(id);
  } catch (error) {
    console.error('Conversation 로드 실패:', error);
    return undefined;
  }
}

/**
 * 대화 삭제
 */
export async function deleteConversation(id: string): Promise<void> {
  try {
    await db.conversations.delete(id);
  } catch (error) {
    console.error('Conversation 삭제 실패:', error);
    throw error;
  }
}

/**
 * 대화 검색 (제목으로)
 */
export async function searchConversations(query: string): Promise<Conversation[]> {
  try {
    const conversations = await db.conversations
      .where('title')
      .startsWithIgnoreCase(query)
      .toArray();
    
    return conversations;
  } catch (error) {
    console.error('Conversation 검색 실패:', error);
    return [];
  }
}

/**
 * 데이터베이스 통계 정보
 */
export async function getStorageStats(): Promise<{ count: number; estimatedSize: string }> {
  try {
    const count = await db.conversations.count();
    const allData = await db.conversations.toArray();
    const jsonSize = JSON.stringify(allData).length;
    const estimatedSize = `${(jsonSize / 1024 / 1024).toFixed(2)} MB`;
    
    return { count, estimatedSize };
  } catch (error) {
    console.error('저장소 통계 조회 실패:', error);
    return { count: 0, estimatedSize: '0 MB' };
  }
}

// 기존 localStorage 기반 함수들과의 호환성을 위한 동기식 래퍼
// WARNING: 이들은 비동기 작업을 동기처럼 사용하므로 가능한 한 새로운 비동기 함수를 사용하세요

/**
 * @deprecated 비동기 saveConversations()를 사용하세요
 */
export function saveConversationsSync(conversations: Conversation[]): void {
  console.warn('saveConversationsSync는 deprecated입니다. saveConversations()를 사용하세요.');
  saveConversations(conversations).catch(console.error);
}

/**
 * @deprecated 비동기 loadConversations()를 사용하세요  
 */
export function loadConversationsSync(): Conversation[] {
  console.warn('loadConversationsSync는 deprecated입니다. loadConversations()를 사용하세요.');
  // 동기식으로는 빈 배열만 반환
  return [];
}

// 데이터베이스는 자동으로 초기화됩니다