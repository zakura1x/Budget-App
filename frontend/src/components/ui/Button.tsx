import type { ButtonHTMLAttributes } from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'md' | 'lg';

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent text-on-accent active:brightness-95',
  secondary: 'bg-surface-2 text-ink active:bg-line',
  ghost: 'bg-transparent text-accent active:bg-accent/10',
  danger: 'bg-danger text-white active:brightness-95',
};

// Both sizes clear the 44px minimum touch target.
const SIZES: Record<Size, string> = {
  md: 'min-h-tap px-4 text-body font-semibold rounded-full',
  lg: 'min-h-[3.25rem] px-5 text-headline rounded-full',
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
        'inline-flex select-none items-center justify-center gap-2 transition active:scale-[0.98]',
        'disabled:pointer-events-none disabled:opacity-40',
        VARIANTS[variant],
        SIZES[size],
        block ? 'w-full' : '',
        className,
      ].join(' ')}
      {...rest}
    />
  );
}
