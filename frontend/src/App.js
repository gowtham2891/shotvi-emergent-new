import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";

import Landing from "@/pages/Landing";
import Auth from "@/pages/Auth";
import Dashboard from "@/pages/Dashboard";
import Upload from "@/pages/Upload";
import ClipsGallery from "@/pages/ClipsGallery";
import Editor from "@/pages/Editor";
import ExportPage from "@/pages/Export";

function App() {
  return (
    <div className="App bg-[#060608] min-h-screen">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/auth" element={<Auth />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/clips/:projectId" element={<ClipsGallery />} />
          <Route path="/editor/:clipId" element={<Editor />} />
          <Route path="/export/:clipId" element={<ExportPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" richColors />
    </div>
  );
}

export default App;
