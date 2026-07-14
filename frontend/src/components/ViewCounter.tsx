import { useEffect, useState } from "react";

// GoatCounter's site-wide visitor counter. The `TOTAL.json` endpoint returns the
// cumulative pageview count for the whole site as a pre-formatted string, e.g.
// { "count": "1,234" }. It only responds once the "allow using the visitor counter"
// setting is enabled in the GoatCounter site settings; until then it 403s and we
// render nothing rather than show a broken widget.
const COUNTER_URL = "https://niw-stats.goatcounter.com/counter/TOTAL.json";

export function ViewCounter() {
  const [count, setCount] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(COUNTER_URL, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: { count?: string | number }) => {
        if (data && data.count != null) setCount(String(data.count));
      })
      .catch(() => {
        /* setting not enabled yet, offline, or blocked: show nothing */
      });
    return () => ctrl.abort();
  }, []);

  if (count === null) return null;
  return (
    <div className="view-count" title="Total page views, counted privately with GoatCounter (no cookies).">
      {count} views
    </div>
  );
}
