import { defineConfig } from 'vite';

// 정적 JSON만 읽는 앱이라 백엔드 설정은 없다. base './' 로 빌드 결과를 아무 경로에서나 열 수 있게 한다.
export default defineConfig({
  base: './',
  server: { port: 5173 },
});
