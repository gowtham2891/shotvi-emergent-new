import "@/App.css";
import { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";

import Landing from "@/pages/Landing";
import Auth from "@/pages/Auth";
import Dashboard from "@/pages/Dashboard";
import Upload from "@/pages/Upload";
import ClipsGallery from "@/pages/ClipsGallery";
import Editor from "@/pages/Editor";
import ExportPage from "@/pages/Export";
import { useAppStore } from "@/store/useAppStore";
import RequireAuth from "@/components/RequireAuth";

function App() {
  const initAuth = useAppStore((s) => s.initAuth);
  useEffect(() => initAuth(), [initAuth]);

  return (
    <div className="App bg-[#060608] min-h-screen">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/auth" element={<Auth />} />
          <Route path="/dashboard" element={<RequireAuth><Dashboard /></RequireAuth>} />
          <Route path="/upload" element={<RequireAuth><Upload /></RequireAuth>} />
          <Route path="/clips/:projectId" element={<RequireAuth><ClipsGallery /></RequireAuth>} />
          <Route path="/editor/:clipId" element={<RequireAuth><Editor /></RequireAuth>} />
          <Route path="/export/:clipId" element={<RequireAuth><ExportPage /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" richColors />
    </div>
  );
}

export default App;
