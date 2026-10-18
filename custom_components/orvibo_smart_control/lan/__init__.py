"""Local-area transport for the fused ORVIBO integration (Stage 1).

Ported from the LAN source implementation: UDP gateway discovery, TCP gateway connections, gateway lifecycle management,
strict packet encoding/decoding, and log redaction. Currently only the state-receive path is connected; control routing will follow in phase 2.
"""

from .control_adapter import LanControlAdapter
from .gateway_manager import GatewayManager
from .privacy import mask_host, mask_identifier

__all__ = ["GatewayManager", "LanControlAdapter", "mask_host", "mask_identifier"]
