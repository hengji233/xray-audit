from __future__ import annotations

import time

from xray_audit.parser import parse_line


def main() -> None:
    sample = "2026/02/18 10:00:00.123456 from 1.2.3.4:12345 accepted tcp:example.com:443 [socks-in -> direct] email: user@example.com"
    total = 200000

    t0 = time.perf_counter()
    for _ in range(total):
        parse_line(sample)
    t1 = time.perf_counter()

    qps = total / (t1 - t0)
    print(f"parsed={total} elapsed={(t1 - t0):.4f}s qps={qps:.2f}")


if __name__ == "__main__":
    main()
