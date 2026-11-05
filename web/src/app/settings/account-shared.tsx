// Pieces shared by the account cards: a loose row type, the account API call
// with a friendlier offline message, and the password input.
import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError, request } from '@/lib/api';

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Row = Record<string, any>;
/* eslint-enable @typescript-eslint/no-explicit-any */

export async function api<T>(path: string, body?: unknown) {
  try {
    return await request<T>(path, body);
  } catch (error) {
    if (error instanceof ApiError && error.status === 0) throw new Error('无法连接账号服务，请检查连接后重试');
    throw error;
  }
}

/** A password input with a show / hide toggle; pasting is never blocked. */
export function PasswordInput({ id, label, autoComplete, value, onChange, disabled }: { id: string; label: string; autoComplete: string; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  const [visible, setVisible] = useState(false);
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <div className="flex gap-2">
        <Input
          id={id}
          type={visible ? 'text' : 'password'}
          autoComplete={autoComplete}
          minLength={8}
          maxLength={128}
          required
          disabled={disabled}
          value={value}
          onChange={event => onChange(event.target.value)}
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={(visible ? '隐藏' : '显示') + label}
          aria-controls={id}
          aria-pressed={visible}
          disabled={disabled}
          onClick={() => setVisible(!visible)}
        >
          {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </Button>
      </div>
    </Field>
  );
}
