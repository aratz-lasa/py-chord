import asyncio
import math
from contextlib import asynccontextmanager
from hashlib import sha1
from typing import Any

from . import node as NodeFactory
from .abc import INode
from .errors import NodeLeaveError, NodeRPCError, InvalidRPC
from .network import TIMEOUT, FINGER_AMOUNT


class Request:
    def __init__(self, reader=None, writer=None, opcode=None, payload=None):
        self.reader = reader
        self.writer = writer
        self.opcode = opcode
        self.payload = payload


# GENERAL
SEPARATOR = b"#"

# OPCODES
IS_ALIVE_OPCODE = 0
GET_PREDECESSOR_OPCODE = 1
SET_PREDECESSOR_OPCODE = 2
GET_SUCCESSOR_OPCODE = 3
SET_SUCCCESSOR_OPCODE = 4
FIND_SUCCCESSOR_OPCODE = 5
UPDATE_FINGER_TABLE_OPCODE = 6
STORE_OPCODE = 7
GET_OPCODE = 8
CLOSEST_PRECEDING_FINGER_OPCODE = 9
NOTIFY_OPCODE = 10

# RESPONSES
OK_RESPONSE = 1


# Client
async def store(dst: INode, value: bytes) -> int:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = value
        request = _dump_request(STORE_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        raw_key = await reader.read(FINGER_AMOUNT // 8)
        key = int.from_bytes(raw_key, "big")
        return key


async def get(dst: INode, key: int) -> Any:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = key.to_bytes(FINGER_AMOUNT // 8, "big")
        request = _dump_request(GET_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        value_length = (await reader.readuntil(SEPARATOR))[:-1]
        value_length = int.from_bytes(value_length, "big")
        return await reader.read(value_length)


async def is_alive(dst: INode) -> bool:
    try:
        async with _open_node_connection(dst) as conn:
            reader, writer = conn[0], conn[1]
            payload = b""
            request = _dump_request(IS_ALIVE_OPCODE, payload)
            writer.write(request)
            await writer.drain()
            is_alive = bool(int.from_bytes((await reader.read(1)), "big"))
            return is_alive
    except NodeLeaveError:
        return False


async def closest_preceding_finger(dst: INode, id: int) -> INode:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = id.to_bytes(FINGER_AMOUNT // 8, "big")
        request = _dump_request(CLOSEST_PRECEDING_FINGER_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        raw_node = await _read_node(reader)
        return _load_node(raw_node)


async def find_successor(dst: INode, id: int) -> INode:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = id.to_bytes(FINGER_AMOUNT // 8, "big")
        request = _dump_request(FIND_SUCCCESSOR_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        raw_node = await _read_node(reader)
        return _load_node(raw_node)


async def notify(dst: INode, node: INode) -> None:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = _dump_node(node)
        request = _dump_request(NOTIFY_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        await _check_ok(reader)


async def update_finger_table(dst: INode, node: INode, index: int) -> None:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = _dump_node(node) + SEPARATOR + index.to_bytes(
            math.ceil(math.log(FINGER_AMOUNT, 2)), "big")
        request = _dump_request(UPDATE_FINGER_TABLE_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        await _check_ok(reader)


async def get_successor(dst: INode) -> INode:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = b""
        request = _dump_request(GET_SUCCESSOR_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        raw_node = await _read_node(reader)
        return _load_node(raw_node)


async def set_successor(dst: INode, node: INode) -> None:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = _dump_node(node)
        request = _dump_request(SET_SUCCCESSOR_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        await _check_ok(reader)


async def get_predecessor(dst: INode) -> INode:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = b""
        request = _dump_request(GET_PREDECESSOR_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        raw_node = await _read_node(reader)
        return _load_node(raw_node)


async def set_predecessor(dst: INode, node: INode) -> None:
    async with _open_node_connection(dst) as conn:
        reader, writer = conn[0], conn[1]
        payload = _dump_node(node)
        request = _dump_request(SET_PREDECESSOR_OPCODE, payload)
        writer.write(request)
        await writer.drain()
        await _check_ok(reader)


# Server
async def handle_request(src: INode, request: Request) -> None:
    reader = request.reader
    writer = request.writer
    if request.opcode == STORE_OPCODE:
        value = request.payload
        key = await src.store(value)
        writer.write(key.to_bytes(FINGER_AMOUNT // 8,
                                  "big"))  # Send back the key
        await writer.drain()
    elif request.opcode == GET_OPCODE:
        key = int.from_bytes(request.payload, "big")
        value = await src.get(key)
        value_length = len(value)
        length_bytes_amount = _get_int_bytes_amount(value_length)
        data = value_length.to_bytes(length_bytes_amount,
                                     "big") + SEPARATOR + value
        writer.write(data)
        await writer.drain()
    elif request.opcode == IS_ALIVE_OPCODE:
        is_alive = await src._is_alive()
        writer.write(bytes([int(is_alive)]))
        await writer.drain()
    elif request.opcode == CLOSEST_PRECEDING_FINGER_OPCODE:
        id = int.from_bytes(request.payload, "big")
        node = await src._closest_preceding_finger(id)
        writer.write(_dump_node(node))
        await writer.drain()
    elif request.opcode == FIND_SUCCCESSOR_OPCODE:
        id = int.from_bytes(request.payload, "big")
        successor = await src._find_successor(id)
        writer.write(_dump_node(successor))
        await writer.drain()
    elif request.opcode == NOTIFY_OPCODE:
        node = _load_node(request.payload)
        await src._notify(node)
        _send_ok(writer)
        await writer.drain()
    elif request.opcode == UPDATE_FINGER_TABLE_OPCODE:
        raw_node, raw_index = request.payload.rsplit(SEPARATOR, 1)
        node = _load_node(raw_node)
        index = int.from_bytes(raw_index, "big")
        await src._update_finger_table(node, index)
        _send_ok(writer)
        await writer.drain()
    elif request.opcode == GET_PREDECESSOR_OPCODE:
        predecessor = await src._get_predecessor()
        writer.write(_dump_node(predecessor))
        await writer.drain()
    elif request.opcode == SET_PREDECESSOR_OPCODE:
        predecessor = _load_node(request.payload)
        await src._set_predecessor(predecessor)
        _send_ok(writer)
        await writer.drain()
    elif request.opcode == GET_SUCCESSOR_OPCODE:
        successor = await src._get_successor()
        writer.write(_dump_node(successor))
        await writer.drain()
    elif request.opcode == SET_SUCCCESSOR_OPCODE:
        successor = _load_node(request.payload)
        await src._set_successor(successor)
        _send_ok(writer)
        await writer.drain()
    else:
        raise InvalidRPC()
    writer.close()


# General
def _dump_request(opcode: int, payload: bytes) -> bytes:
    payload_length = len(payload)
    length_bytes_amount = _get_int_bytes_amount(payload_length)

    return bytes([opcode]) + SEPARATOR + payload_length.to_bytes(
        length_bytes_amount, "big") + SEPARATOR + payload


def _dump_node(node: INode) -> bytes:
    return node.ip.encode() + SEPARATOR + node.port.to_bytes(2, "big")


async def _read_node(reader) -> bytes:
    raw_node = b""
    node_chunk = await reader.readuntil(SEPARATOR)
    raw_node += node_chunk
    raw_node += await reader.read(2)  # PORT: 2 bytes
    return raw_node


def _load_node(raw_node: bytes) -> INode:
    splitted_data = raw_node.split(SEPARATOR)
    ip = splitted_data[0].decode()
    port = int.from_bytes(splitted_data[1], "big")
    return NodeFactory.RemoteNode(ip, port)


def _get_key_from_value(value):
    hash = sha1()
    hash.update(value)
    key = int.from_bytes(hash.digest(), "big")
    return key


def _send_ok(writer):
    writer.write(bytes([OK_RESPONSE]))


async def _check_ok(reader):
    ok = int.from_bytes(await reader.read(1), "big") == OK_RESPONSE
    if not ok:
        raise NodeRPCError()


def _get_int_bytes_amount(number: int):
    if number == 0:
        return 1
    return math.ceil(math.log(number, 256))


@asynccontextmanager
async def _open_node_connection(dst: INode):
    conn = asyncio.open_connection(dst.ip, dst.port)
    try:
        reader, writer = await asyncio.wait_for(conn, TIMEOUT)
        yield (
            reader,
            writer,
        )
    except (asyncio.TimeoutError, ConnectionError):
        raise NodeLeaveError()
    finally:
        if "writer" in locals():
            writer.close()
