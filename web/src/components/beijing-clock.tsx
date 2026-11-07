import { useEffect, useState } from 'react';

const DATE = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'full' });
const TIME = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false, timeStyle: 'medium' });

/** Market times are Beijing time regardless of where the browser is. */
export function BeijingClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <p className="flex min-w-0 flex-wrap items-baseline gap-x-3 text-sm text-muted-foreground">
      <span className="hidden sm:inline">{DATE.format(now)}</span>
      <span>
        北京时间 <time className="font-medium text-foreground tabular-nums">{TIME.format(now)}</time>
      </span>
    </p>
  );
}
