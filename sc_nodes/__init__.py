import logging

from nonoha_core.node_registry import NodeRegistry

from .sclang_node import SclangNode

logger = logging.getLogger(__name__)


def register_nodes(registry: NodeRegistry):
    logger.info("sc-nodes plugin loaded")

    registry.register_node("Sclang", SclangNode)


def finalize():
    logger.info("sc-nodes plugin finalized")
