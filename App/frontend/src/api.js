// 백엔드 API URL 상수
// localhost 대신 127.0.0.1 명시 — Windows 11에서 localhost가 ::1(IPv6)로
// 해석되면 127.0.0.1(IPv4)로 바인딩된 Flask에 연결 실패하는 문제 방지
export const API_BASE = 'http://127.0.0.1:5001'
