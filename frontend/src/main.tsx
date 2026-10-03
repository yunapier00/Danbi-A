import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import ChatPage from "./chat/ChatPage";
import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./base.css";

// 개발자 페이지는 채팅 사용자에게 필요 없으므로 따로 불러온다
const DevPage = lazy(() => import("./dev/DevPage"));

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
