"""
The flow table: which packet goes to which flow, and when a flow ends (port of FlowGenerator at 13a0615).

- A flow is keyed by its first packet's (src, dst, sport, dport, protocol); a packet joins the flow
  under its own key or under the reversed one. The key's orientation is the Flow ID.
- A flow ends when a packet arrives more than flow_timeout after the flow's start, or a SYN arrives
  after its TCP teardown (FIN both ways, then ACK; or RST). The packet then starts the next flow. A TCP
  connection split by the timeout continues in the same direction, and Total TCP Flow Time accumulates
  over the pieces and the gaps between them.
- An ICMP flow ends when a packet differs in both code and type (the reference says AND; kept).
- Flows still open at the end of the capture are flushed.

The reference keeps every flow in memory until a packet for it arrives or the capture ends. Here a flow
that is already past the timeout is emitted during the capture and leaves a small record behind, so the
next packet with its key behaves exactly as in the reference while memory stays bounded.
"""

from .flow import FIRST_FIN, READY_FOR_TERMINATION, SECOND_FIN, Flow
from .packet import ACK, FIN, ICMP, RST, SYN, TCP

FLOW_TIMEOUT = 120_000_000          # µs, from the reference's CLI
ACTIVITY_TIMEOUT = 5_000_000        # µs
SWEEP_EVERY = 10_000_000            # µs of capture time between looks for timed-out flows
# Emit early only flows this far past the timeout, so a slightly out-of-order packet can't still join them
SWEEP_MARGIN = 10_000_000


class _Ended:
    """What the next packet with an emitted flow's key needs from it."""

    __slots__ = ("src", "dst", "sport", "dport", "cumulative", "last_seen", "tcp_state")

    def __init__(self, flow: Flow):
        self.src, self.dst, self.sport, self.dport = flow.src, flow.dst, flow.sport, flow.dport
        self.cumulative, self.last_seen, self.tcp_state = flow.cumulative, flow.last_seen, flow.tcp_state


class FlowGenerator:

    def __init__(self, flow_timeout=FLOW_TIMEOUT, activity_timeout=ACTIVITY_TIMEOUT):
        self.flow_timeout = flow_timeout
        self.activity_timeout = activity_timeout
        self.flows: dict[tuple, Flow | _Ended] = {}
        self.finished: list[Flow] = []          # emitted flows; the caller takes them away
        self._next_sweep = None

    def add(self, p) -> None:
        flows = self.flows
        key = (p.src, p.dst, p.sport, p.dport, p.proto)
        flow = flows.get(key)
        if flow is None:
            reverse = (p.dst, p.src, p.dport, p.sport, p.proto)
            flow = flows.get(reverse)
            if flow is None:
                flows[key] = Flow(p, key, self.activity_timeout)
                self._maybe_sweep(p.ts)
                return
            key = reverse

        ts, flags = p.ts, p.flags
        ended = type(flow) is _Ended
        if ended or ts - flow.start > self.flow_timeout or (flow.tcp_state == READY_FOR_TERMINATION and flags & SYN):
            if not ended:
                self._finish(flow)
            # A SYN (not SYN-ACK) after the teardown, or any non-TCP packet, starts afresh; otherwise this
            # is the same TCP connection after a timeout, continued in its direction
            if (flow.tcp_state == READY_FOR_TERMINATION and flags & SYN and not flags & ACK) or p.proto != TCP:
                flows[key] = Flow(p, key, self.activity_timeout)
            else:
                piece = Flow(p, key, self.activity_timeout, flow.src, flow.dst, flow.sport, flow.dport)
                piece.cumulative = flow.cumulative + (ts - flow.last_seen)
                flows[key] = piece
        elif flags & FIN:
            flow.update_active_idle(ts, self.activity_timeout)
            flow.add(p)
            if flow.tcp_state is None:
                flow.tcp_state = FIRST_FIN
            elif flow.tcp_state == FIRST_FIN and flow.fwd_fin > 0 and flow.bwd_fin > 0:
                flow.tcp_state = SECOND_FIN
        elif flags & RST:
            flow.update_active_idle(ts, self.activity_timeout)
            flow.add(p)
            flow.tcp_state = READY_FOR_TERMINATION
        elif flags & ACK:
            flow.update_active_idle(ts, self.activity_timeout)
            flow.add(p)
            if flow.tcp_state == SECOND_FIN:
                flow.tcp_state = READY_FOR_TERMINATION
        elif flow.protocol == ICMP and flow.icmp_code != p.icmp_code and flow.icmp_type != p.icmp_type:
            self.finished.append(flow)
            flows[key] = Flow(p, key, self.activity_timeout)
        else:
            flow.update_active_idle(ts, self.activity_timeout)
            flow.add(p)
        self._maybe_sweep(ts)

    def _finish(self, flow: Flow) -> None:
        if flow.protocol == TCP:
            flow.cumulative += flow.last_seen - flow.start
        self.finished.append(flow)

    def _maybe_sweep(self, now) -> None:
        if self._next_sweep is None:
            self._next_sweep = now + SWEEP_EVERY
        elif now >= self._next_sweep:
            self._next_sweep = now + SWEEP_EVERY
            limit = now - self.flow_timeout - SWEEP_MARGIN
            flows = self.flows
            for key, flow in list(flows.items()):
                if type(flow) is Flow and flow.start < limit:
                    self._finish(flow)
                    flows[key] = _Ended(flow)

    def flush(self) -> None:
        """End of capture: emit every open flow (dumpLabeledCurrentFlow)."""
        for flow in self.flows.values():
            if type(flow) is Flow:
                self._finish(flow)
        self.flows.clear()
