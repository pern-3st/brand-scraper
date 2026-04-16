"use client";

interface LoginPausedBannerProps {
  reason: "login" | "captcha";
  onContinue: () => void;
  onCancel: () => void;
}

const COPY: Record<LoginPausedBannerProps["reason"], { title: string; body: string }> = {
  login: {
    title: "Login required",
    body: "Please log in to Shopee in the browser window, then click Continue.",
  },
  captcha: {
    title: "Captcha required",
    body: "Please solve the captcha in the browser window, then click Continue.",
  },
};

export default function LoginPausedBanner({
  reason,
  onContinue,
  onCancel,
}: LoginPausedBannerProps) {
  const { title, body } = COPY[reason];
  return (
    <div className="rounded-2xl bg-amber-50 ring-1 ring-amber-300/70 shadow-md shadow-amber-200/40 p-5 flex items-start gap-4">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700">
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M12 9v4" />
          <path d="M12 17h.01" />
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
        </svg>
      </div>
      <div className="flex-1 min-w-0">
        <h3 className="text-sm font-semibold text-amber-900">{title}</h3>
        <p className="mt-1 text-sm text-amber-800/90">{body}</p>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={onContinue}
            className="rounded-xl bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-600 transition-colors"
          >
            Continue
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-xl bg-white/80 px-4 py-2 text-sm font-medium text-amber-800 ring-1 ring-amber-300 hover:bg-white transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
