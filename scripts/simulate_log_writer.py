from __future__ import annotations

import argparse
import random
import time
from datetime import datetime


def now_str() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")


def gen_line(i: int) -> str:
    if i % 7 == 0:
        return f"{now_str()} 8.8.8.8 got answer: demo{i}.example.com. -> [1.1.1.{i % 255}] {random.randint(1, 30)}ms"
    return f"{now_str()} from 10.0.0.{i % 255}:12345 accepted tcp:demo{i % 100}.example.com:443 [socks-in -> direct] email: user{i % 10}@example.com"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--rate", type=int, default=1000)
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()

    total = args.rate * args.seconds
    interval = 1.0 / args.rate

    with open(args.path, "a", encoding="utf-8") as f:
        for i in range(total):
            f.write(gen_line(i) + "\n")
            if interval > 0:
                time.sleep(interval)


if __name__ == "__main__":
    main()
