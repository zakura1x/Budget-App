/**
 * The loading skeleton, shown while the app asks the server who you are - and,
 * from Phase 4, while the first decrypt of your data happens (~0.5 s). Shaped
 * like the home screen so the swap is not a jump.
 */
export function Splash() {
  return (
    <div className="mx-auto min-h-dvh max-w-app px-safe pt-safe" aria-busy="true" aria-label="Loading">
      <div className="pb-3 pt-4">
        <div className="skeleton h-4 w-32 rounded-md" />
        <div className="skeleton mt-2 h-8 w-40 rounded-lg" />
      </div>
      <div className="flex flex-col items-center rounded-card bg-surface py-7 shadow-card">
        <div className="skeleton h-[232px] w-[232px] rounded-full" />
        <div className="mt-6 grid w-full grid-cols-2 gap-6 px-8">
          <div className="skeleton h-10 rounded-lg" />
          <div className="skeleton h-10 rounded-lg" />
        </div>
      </div>
    </div>
  );
}
