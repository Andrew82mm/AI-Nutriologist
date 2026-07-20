// Inline Lucide icons, vendored from the design prototype (web/…dc.html). The
// design system draws icons as inline SVG on `currentColor` — there are no
// separate icon files — so they live here as small components. Each takes the
// stroke color from `currentColor` and sizes via the `size` prop.

const svg = (size, children, extra = {}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.2"
    strokeLinecap="round"
    strokeLinejoin="round"
    {...extra}
  >
    {children}
  </svg>
);

export const IconDiary = ({ size = 23 }) =>
  svg(size, (
    <>
      <path d="M4 4a2 2 0 0 1 2-2h11a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2z" />
      <path d="M4 18a2 2 0 0 1 2-2h12M8 7h6M8 11h6" />
    </>
  ));

export const IconFridge = ({ size = 23 }) =>
  svg(size, (
    <>
      <rect x="5" y="2" width="14" height="20" rx="2" />
      <path d="M5 10h14M9 5v2M9 13v3" />
    </>
  ));

export const IconPlan = ({ size = 23 }) =>
  svg(size, (
    <>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M3 9h18M8 2v4M16 2v4M9 15l2 2 4-4" />
    </>
  ));

export const IconProfile = ({ size = 23 }) =>
  svg(size, (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ));

export const IconChat = ({ size = 17 }) =>
  svg(size, (
    <>
      <path d="M12 3a9 9 0 0 0-9 9 8.6 8.6 0 0 0 .9 3.8L3 21l5.2-.9A9 9 0 1 0 12 3z" />
      <path d="M8.5 12h.01M12 12h.01M15.5 12h.01" />
    </>
  ), { strokeWidth: 2.4 });

export const IconArrowRight = ({ size = 18 }) =>
  svg(size, <path d="M5 12h14M13 6l6 6-6 6" />, { strokeWidth: 2.4 });

export const IconChevronRight = ({ size = 16 }) =>
  svg(size, <path d="M9 18l6-6-6-6" />, { strokeWidth: 2.6 });

export const IconSun = ({ size = 19 }) =>
  svg(size, (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ), { strokeWidth: 2.4 });

export const IconMoon = ({ size = 19 }) =>
  svg(size, <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />, { strokeWidth: 2.4 });
