import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/ui/tooltip';
import { applyTheme, storedTheme } from '@/lib/theme';
import { App } from '@/app/App';

applyTheme(storedTheme());
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider>
      <App />
      <Toaster position="top-center" />
    </TooltipProvider>
  </StrictMode>,
);
