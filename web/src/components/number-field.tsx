// Number input for amounts and counts. The shadcn registry has no Number Field
// for Base UI yet (checked with `shadcn search`), so this composes Base UI's own
// NumberField primitive with the Input styles. Keyboard stepping, clamping and
// focus handling come from Base UI; nothing here re-implements them.
import { NumberField as NumberFieldPrimitive } from '@base-ui/react/number-field';
import { Minus, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';

export function NumberField({
  id,
  value,
  onValueChange,
  min,
  max,
  step = 1,
  disabled,
  required,
  className,
  'aria-describedby': describedBy,
}: {
  id?: string;
  value: number | null;
  onValueChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  required?: boolean;
  className?: string;
  'aria-describedby'?: string;
}) {
  return (
    <NumberFieldPrimitive.Root
      id={id}
      value={value}
      onValueChange={next => onValueChange(next)}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      required={required}
      className={cn('w-full', className)}
    >
      <NumberFieldPrimitive.Group className="flex h-8 w-full items-stretch overflow-hidden rounded-lg border border-input focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30">
        <NumberFieldPrimitive.Decrement
          aria-label="减少"
          className="flex w-8 items-center justify-center text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
        >
          <Minus className="size-3.5" aria-hidden="true" />
        </NumberFieldPrimitive.Decrement>
        <NumberFieldPrimitive.Input
          aria-describedby={describedBy}
          className="w-full min-w-0 bg-transparent px-2 text-center text-base tabular-nums outline-none md:text-sm"
        />
        <NumberFieldPrimitive.Increment
          aria-label="增加"
          className="flex w-8 items-center justify-center text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
        >
          <Plus className="size-3.5" aria-hidden="true" />
        </NumberFieldPrimitive.Increment>
      </NumberFieldPrimitive.Group>
    </NumberFieldPrimitive.Root>
  );
}
