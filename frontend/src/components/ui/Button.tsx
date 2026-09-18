import type { ButtonHTMLAttributes } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'md' | 'lg';

// Neo-brutalism: every filled button is outlined, lifted on a hard shadow,
// and sinks onto it while pressed (`.press`). Ghost stays flat - it is a link.
const VARIANTS: Record<Variant, string> = {
  primary: 'press bg-accent text-on-accent',
  secondary: 'press bg-surface text-ink',
  ghost: 'bg-transparent text-accent-ink underline-offset-4 active:underline',
  danger: 'press bg-danger text-white',
};

// Both sizes clear the 44px minimum touch target.
const SIZES: Record<Size, string> = {
  md: 'min-h-tap px-4 text-body font-bold rounded-xl',
  lg: 'min-h-[3.25rem] px-5 text-headline font-extrabold rounded-xl',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  block?: boolean;
}

export function Button({ variant = 'primary', size = 'md', block = false, className = '', type = 'button', ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={[
        'inline-flex select-none items-center justify-center gap-2',
        'disabled:pointer-events-none disabled:opacity-40 disabled:shadow-edge',
        VARIANTS[variant],
        SIZES[size],
        block ? 'w-full' : '',
        className,
      ].join(' ')}
      {...rest}
    />
  );
}
