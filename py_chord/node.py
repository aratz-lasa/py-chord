import asyncio
from hashlib import sha1
from typing import Any

from . import rpc
from .abc import INode, INodeServer
from .errors import InvalidRPC, NodeLeaveError
from .network import is_between_ids, ChordNetwork, CHORD_PORT, MAINTENANCE_FREQUENCY


def node_leave_corrector(func, retry_time=MAINTENANCE_FREQUENCY, max_retries=2):
    async def wrapper(self, *args, retries=0, **kwargs):
        try:
            return await func(self, *args, **kwargs)
        except NodeLeaveError:
            if retries >= max_retries:
                raise NodeLeaveError(f"Exceeded maximum retries amount: {max_retries}")
            self.local_node.network.remove_left_node(self)
            await asyncio.sleep(retry_time)
            await wrapper(self, *args, retries=retries + 1, **kwargs)

    return wrapper


class Node(INode, INodeServer):
    def __init__(self, ip: str, port: int = CHORD_PORT):
        super().__init__(ip, port)
        self.network = ChordNetwork(self)
        self.hash_table = {}
        self._predecessor = None
        self._server = None
        self._alive = False
        self._maintenance_task = None

    async def store(self, value: bytes) -> int:
        if not isinstance(value, bytes):
            raise InvalidRPC()
        key = self._get_key_from_value(value)
        successor = await self._find_successor(key)
        if successor == self:
            logger.debug(f"({self.id}) - Stored value in local node: {key}")
            self.hash_table[key] = value
        else:
            await successor.store(value)
        return key

    async def get(self, key: int) -> Any:
        successor = await self._find_successor(key)
        if successor == self:
            return self.hash_table.get(key)
        else:
            return await successor.get(key)

    async def leave(self) -> None:
        await self._stop_server()

    async def _start_server(self):
        self._server = await asyncio.start_server(
            self._handle_request, self.ip, self.port
        )
        self._maintenance_task = asyncio.create_task(self._run_maintenance_task())
        self._alive = True

    async def _stop_server(self):
        if self._maintenance_task:
            self._maintenance_task.cancel()
        self._server.close()
        await self._server.wait_closed()
        self._alive = False

    async def _is_alive(self):
        return self._alive

    async def _closest_preceding_finger(self, id: int) -> INode:
        for finger in reversed(self.network.finger_table):
            if finger.node and is_between_ids(finger.node.id, self.id, id):
                return finger.node
        return self

    @node_leave_corrector
    async def _find_successor(self, id: int) -> INode:
        predecessor = await self.network._find_predecessor(id)
        successor = await predecessor._get_successor()
        return successor

    async def _notify(self, node: INode) -> None:
        if not self._predecessor or is_between_ids(
            node.id, self._predecessor.id, self.id
        ):
            self._predecessor = node

    async def _update_finger_table(self, node: INode, index: int) -> None:
        finger = self.network.finger_table[index]
        if not finger.node or is_between_ids(
            node.id, finger.start, finger.node.id, first_equality=True
        ):  # Changed from original pseudo-code
            finger.node = node
            if (
                self._predecessor and self._predecessor != self
            ):  # Check for avoiding error or recursive call
                await self._predecessor._update_finger_table(node, index)

    async def _get_successor(self) -> INode:
        for finger in self.network.finger_table:
            if finger.node:
                return finger.node
        return self

    async def _set_successor(self, node: INode) -> None:
        self.network.finger_table[0].node = node

    async def _get_predecessor(self) -> INode:
        if self._predecessor:
            return self._predecessor
        for finger in reversed(self.network.finger_table):
            if finger.node:
                return finger.node
        return self

    async def _set_predecessor(self, node: INode) -> None:
        self._predecessor = node

    async def _handle_request(self, reader, writer) -> None:
        opcode = (await reader.readuntil(rpc.SEPARATOR))[:-1]
        opcode = int.from_bytes(opcode, "big")
        payload_length = (await reader.readuntil(rpc.SEPARATOR))[:-1]
        payload_length = int.from_bytes(payload_length, "big")
        payload = await reader.read(payload_length)
        logger.debug(
            f"Request: OPCODE {opcode} - PAYLOAD-LENGTH {payload_length} - PAYLOAD {payload[:20]}"
        )
        request = rpc.Request(reader, writer, opcode, payload)
        await rpc.handle_request(self, request)
        writer.close()

    async def _run_maintenance_task(self):
        while True:
            await asyncio.sleep(MAINTENANCE_FREQUENCY)
            await self.network.mantain()

    def _get_key_from_value(self, value):
        hash = sha1()
        hash.update(value)
        key = int.from_bytes(hash.digest(), "big")
        return key


class RemoteNode(INode):
    def __init__(self, ip: str, port: int = CHORD_PORT):
        super().__init__(ip, port)

    async def store(self, value: bytes) -> None:
        await rpc.store(self, value)

    async def get(self, key: int) -> Any:
        return await rpc.get(self, key)

    async def _is_alive(self) -> bool:
        return await rpc.is_alive(self)

    async def _closest_preceding_finger(self, id: int) -> INode:
        return await rpc.closest_preceding_finger(self, id)

    async def _find_successor(self, id: int) -> INode:
        return await rpc.find_successor(self, id)

    async def _notify(self, node: INode) -> None:
        return await rpc.notify(self, node)

    async def _update_finger_table(self, node: INode, index: int) -> None:
        return await rpc.update_finger_table(self, node, index)

    async def _get_successor(self) -> INode:
        return await rpc.get_successor(self)

    async def _set_successor(self, node: INode) -> None:
        return await rpc.set_successor(self, node)

    async def _get_predecessor(self) -> INode:
        return await rpc.get_predecessor(self)

    async def _set_predecessor(self, node: INode) -> None:
        return await rpc.set_predecessor(self, node)

    async def leave(self) -> None:
        pass
