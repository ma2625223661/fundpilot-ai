import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { TooltipProvider } from '@/components/ui/tooltip';
import { applyTheme, storedTheme } from '@/lib/theme';
import { LoginApp } from '@/app/LoginApp';

applyTheme(storedTheme());
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider>
      <LoginApp />
    </TooltipProvider>
  </StrictMode>,
);
