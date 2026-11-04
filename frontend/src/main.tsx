import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import ChatPage from "./chat/ChatPage";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./base.css";

// 개발자 페이지는 채팅 사용자에게 필요 없으므로 따로 불러온다
const DevPage = lazy(() => import("./dev/DevPage"));

// 홈 화면 설치(PWA)용 서비스 워커. 빌드한 화면에서만 켠다 (npm run dev에서는 옛 화면 캐시로 헷갈리지 않게)
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => { navigator.serviceWorker.register("/sw.js").catch(() => {}); });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route
          path="/dev"
          element={
            <Suspense fallback={null}>
              <DevPage />
            </Suspense>
          }
        />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
