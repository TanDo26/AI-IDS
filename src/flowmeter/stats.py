"""
Running statistics with the arithmetic of Apache Commons Math 3 SummaryStatistics, which the reference
tool uses: the mean and variance come from its incremental (Welford) moments, not from sum / n, so the
values match it bit for bit. Variance and standard deviation are sample statistics (n - 1).
"""

import math

NAN = float("nan")


class Stat:
    __slots__ = ("n", "m1", "m2", "total", "lo", "hi")

    def __init__(self):
        self.n = 0
        self.m1 = self.m2 = NAN
        self.total = 0.0
        self.lo = self.hi = NAN

    def add(self, d):
        n = self.n + 1
        self.n = n
        self.total += d
        if n == 1:
            self.m1, self.m2 = 0.0 + d, 0.0
            self.lo = self.hi = d
            return
        dev = d - self.m1
        ndev = dev / n
        self.m1 += ndev
        self.m2 += (n - 1) * dev * ndev
        if d < self.lo:
            self.lo = d
        if d > self.hi:
            self.hi = d

    @property
    def mean(self) -> float:
        return self.m1

    @property
    def variance(self) -> float:
        if self.n < 2:
            return NAN if self.n == 0 else 0.0
        return self.m2 / (self.n - 1.0)

    @property
    def std(self) -> float:
        if self.n < 2:
            return NAN if self.n == 0 else 0.0
        return math.sqrt(self.m2 / (self.n - 1.0))
