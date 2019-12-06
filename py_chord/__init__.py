from typing import Tuple
from .network import CHORD_PORT as _CHORD_PORT
from .node import Node as _Node, RemoteNode as _RemoteNode
from .abc import INode


async def join_network(
    my_ip: str = "0.0.0.0", my_port: int = _CHORD_PORT, bootstrap_node: Tuple = None
) -> INode:
    me = _Node(my_ip, my_port)
    await me._start_server()
    if bootstrap_node:
        entry_point = _RemoteNode(bootstrap_node[0], bootstrap_node[1])
    else:
        entry_point = None
    await me.network.join(entry_point)
    return me
