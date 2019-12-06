from .network import CHORD_PORT as _CHORD_PORT
from .node import Node as _Node, RemoteNode as _RemoteNode
from .abc import INode


async def join_network(peer_ip: str = None,
                       peer_port: int = None,
                       my_ip: str = "0.0.0.0",
                       my_port: int = _CHORD_PORT) -> INode:
    me = _Node(my_ip, my_port)
    await me._start_server()
    if peer_ip:
        entry_point = _RemoteNode(peer_ip, peer_port)
    else:
        entry_point = None
    await me.network.join(entry_point)
    return me
