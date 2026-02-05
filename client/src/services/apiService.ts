import axiosClient from '../api/axiosClient';
import type { Message, UploadStatusInfo, DocumentsResponse } from '../types';

/**
 * 메시지 페이로드를 정리하는 함수
 * - sources 객체 제거
 * - 텍스트의 줄바꿈을 공백으로 변환
 */
function cleanMessagesForPayload(messages: Message[]): Message[] {
  return messages.map((message) => ({
    ...message,
    parts: (message.parts || []).map((part) => ({
      ...part,
      text: (part.text || '')
        .replace(/<div class='sources'>[\s\S]*?<\/div>/g, '') // sources 객체 제거
        .replace(/\n+/g, ' ') // 줄바꿈을 공백으로 변환
        .trim(),
    })),
  }));
}

export async function sendChatMessage(messages: Message[]) {
  const cleanedMessages = cleanMessagesForPayload(messages);
  const response = await axiosClient.post('/chat', {
    contents: cleanedMessages,
  });
  return response;
}

export async function streamChatMessage(
  messages: Message[],
  onChunk: (chunk: string) => void
): Promise<string> {
  const cleanedMessages = cleanMessagesForPayload(messages);
  const API_BASE_URL = window.location.origin + '/api';
  
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: cleanedMessages,
    }),
  });

  if (!response.ok) throw new Error('Server Error');
  if (!response.body) throw new Error('ReadableStream not supported');

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let accumulatedText = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    accumulatedText += chunk;
    onChunk(accumulatedText);
  }

  return accumulatedText;
}

export async function getDocuments(): Promise<DocumentsResponse> {
  const response = await axiosClient.get('/documents');
  return response.data;
}

export async function deleteDocument(filename: string) {
  const response = await axiosClient.delete('/documents', {
    params: { filename },
  });
  return response.data;
}

export async function uploadFile(file: File) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await axiosClient.post('/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
}

export async function pollUploadStatus(
  taskId: string,
  onUpdate: (info: UploadStatusInfo) => void
): Promise<UploadStatusInfo> {
  let interval = 2000;
  const maxInterval = 5000;
  const start = Date.now();
  const maxTimeout = 1000 * 60 * 20; // 20 minutes

  while (true) {
    try {
      const response = await axiosClient.get(
        `/upload/status/${encodeURIComponent(taskId)}`
      );
      const info = response.data as UploadStatusInfo;
      onUpdate(info);

      if (info.status === 'done' || info.status === 'failed') {
        return info;
      }

      if (Date.now() - start > maxTimeout) {
        const timeoutInfo: UploadStatusInfo = {
          status: 'failed',
          message: '타임아웃',
          progress: info.progress || 0,
        };
        onUpdate(timeoutInfo);
        throw new Error('Polling timeout');
      }

      await new Promise((r) => setTimeout(r, interval));
      interval = Math.min(interval * 2, maxInterval);
    } catch (err: any) {
      if (err.response?.status === 404) {
        const errorInfo: UploadStatusInfo = {
          status: 'failed',
          message: '작업을 찾을 수 없습니다',
          progress: 0,
        };
        onUpdate(errorInfo);
        return errorInfo;
      }
      throw err;
    }
  }
}
