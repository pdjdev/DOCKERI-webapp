import axios from 'axios';

// 개발 환경: /api 프록시 사용, 프로덕션: 환경변수 사용
const API_BASE_URL = import.meta.env.PROD
  ? import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
  : '/api';

const axiosClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export default axiosClient;
