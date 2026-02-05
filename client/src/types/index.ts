export interface MessagePart {
  text: string;
}

export interface Message {
  role: 'user' | 'model';
  parts: MessagePart[];
  uploadStatus?: UploadStatusInfo;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: string;
}

export interface UploadStatusInfo {
  status: 'uploaded' | 'processing' | 'done' | 'failed';
  message?: string;
  progress?: number;
}

export interface DocumentsResponse {
  documents: string[];
}
