import asyncio
from functools import reduce
from hashlib import sha1
from random import choice
import pytest

from py_chord.network import MAINTENANCE_FREQUENCY
from py_chord.node import Node, RemoteNode
from tests.utils import data

pytestmark = pytest.mark.skip("Running other DHTs tests, and slows down")


loop = asyncio.new_event_loop()

node = None
remote_node_local = None
remote_node_remote = None
remote_nodes = []
IP = "127.0.0.1"
FIRST_REMOTE_PORT = 5555


async def init_one_node():
    global node

    node = Node(IP)
    await node._start_server()


async def init_two_nodes():
    global node, remote_node_local, remote_node_remote, remote_nodes

    node = Node(IP)
    remote_node_local = Node(IP, FIRST_REMOTE_PORT)
    remote_node_remote = RemoteNode(IP, FIRST_REMOTE_PORT)
    remote_nodes.append((remote_node_local, remote_node_remote))
    await node._start_server()
    await remote_node_local._start_server()


async def init_n_nodes(n: int):
    global node, remote_node_local, remote_node_remote, remote_nodes

    node = Node(IP)
    await node._start_server()

    for i in range(n):
        remote_node_local = Node(IP, FIRST_REMOTE_PORT + i)
        remote_node_remote = RemoteNode(IP, FIRST_REMOTE_PORT + i)
        await remote_node_local._start_server()
        remote_nodes.append((remote_node_local, remote_node_remote))


async def stop_nodes():
    await node.leave()
    for local_node, remote_node in remote_nodes:
        await local_node.leave()
    remote_nodes.clear()


def test_is_alive():
    loop.run_until_complete(is_alive())


async def is_alive():
    global node, remote_node_remote

    await init_two_nodes()

    assert await node._is_alive()
    assert await remote_node_remote._is_alive()

    await stop_nodes()

    assert not await node._is_alive()
    assert not await remote_node_remote._is_alive()


def test_join_node():
    loop.run_until_complete(join_first_node())
    loop.run_until_complete(join_two_nodes())
    loop.run_until_complete(join_n_nodes(5))


async def join_first_node():
    global node, remote_node_remote

    await init_one_node()

    network = node.network
    await network.join()
    for finger in network.finger_table:
        assert finger.node == node

    await stop_nodes()


async def join_two_nodes():
    global node, remote_node_remote

    await init_two_nodes()

    remote_network = remote_node_local.network
    nodes = [node, remote_node_local]

    await remote_network.join()
    for finger in remote_network.finger_table:
        assert finger.node == remote_node_local

    network = node.network
    await network.join(remote_node_remote)
    for i, finger in enumerate(network.finger_table):
        expected_node = _get_expected_node(finger.start, nodes)
        assert finger.node == expected_node

    await asyncio.sleep(MAINTENANCE_FREQUENCY)

    for i, finger in enumerate(remote_network.finger_table):
        expected_node = _get_expected_node(finger.start, nodes)
        assert finger.node == expected_node

    await stop_nodes()


async def join_n_nodes(n: int):
    global remote_nodes
    await init_n_nodes(n)

    first_remote_node_local, first_remote_node_remote = (
        remote_nodes[0][0],
        remote_nodes[0][1],
    )
    remote_network = first_remote_node_local.network
    await remote_network.join()
    for finger in remote_network.finger_table:
        assert finger.node == first_remote_node_local

    for local_node, _ in remote_nodes[1:]:
        await local_node.network.join(first_remote_node_remote)

    await asyncio.sleep(MAINTENANCE_FREQUENCY)

    remote_nodes_remote = list(zip(*remote_nodes))[0]
    for local_node, _ in remote_nodes:
        remote_network = local_node.network
        for finger in remote_network.finger_table:
            expected_node = _get_expected_node(finger.start, remote_nodes_remote)
            assert finger.node == expected_node

    await stop_nodes()


def test_store():
    loop.run_until_complete(store_with_two_nodes())
    loop.run_until_complete(store_with_n_nodes(5))


async def store_with_two_nodes():
    await init_two_nodes()
    await remote_node_local.network.join()
    await node.network.join(remote_node_remote)

    content = data.load_file50k()
    hash = sha1()
    hash.update(content)
    key = int.from_bytes(hash.digest(), "big")
    # Local storage
    while _get_expected_node(key, [node, remote_node_local]) != node:
        content += b"a"
        hash = sha1()
        hash.update(content)
        key = int.from_bytes(hash.digest(), "big")

    retrieved_key = await node.store(content)
    assert key == retrieved_key
    retrieved_content = await node.get(key)
    assert content == retrieved_content
    # Remote storage
    while _get_expected_node(key, [node, remote_node_local]) != remote_node_local:
        content += b"a"
        hash = sha1()
        hash.update(content)
        key = int.from_bytes(hash.digest(), "big")

    retrieved_key = await node.store(content)
    assert key == retrieved_key
    retrieved_content = await node.get(key)
    assert content == retrieved_content

    await stop_nodes()


async def store_with_n_nodes(n: int):
    global remote_nodes
    await init_n_nodes(n)
    first_remote_node_local, first_remote_node_remote = (
        remote_nodes[0][0],
        remote_nodes[0][1],
    )
    remote_network = first_remote_node_local.network
    await remote_network.join()
    for local_node, _ in remote_nodes[1:]:
        await local_node.network.join(first_remote_node_remote)
    await asyncio.sleep(MAINTENANCE_FREQUENCY)
    remote_nodes_remote = list(zip(*remote_nodes))[0]

    content = data.load_file50k()
    hash = sha1()
    hash.update(content)
    key = int.from_bytes(hash.digest(), "big")
    # Local storage
    while _get_expected_node(key, remote_nodes_remote) != first_remote_node_local:
        content += b"a"
        hash = sha1()
        hash.update(content)
        key = int.from_bytes(hash.digest(), "big")

    retrieved_key = await first_remote_node_local.store(content)
    assert key == retrieved_key
    retrieved_content = await first_remote_node_local.get(key)
    assert content == retrieved_content
    # Remote storage for every N nodes
    for remote_node in remote_nodes_remote[1:]:
        while _get_expected_node(key, remote_nodes_remote) != remote_node:
            content += b"a"
            hash = sha1()
            hash.update(content)
            key = int.from_bytes(hash.digest(), "big")

        retrieved_key = await first_remote_node_local.store(content)
        assert key == retrieved_key
        retrieved_content = await first_remote_node_local.get(key)
        assert content == retrieved_content

    await stop_nodes()


def test_failure():
    loop.run_until_complete(failure(5))


async def failure(n: int):
    global remote_nodes
    await init_n_nodes(n)
    first_remote_node_local, first_remote_node_remote = (
        remote_nodes[0][0],
        remote_nodes[0][1],
    )
    remote_network = first_remote_node_local.network
    await remote_network.join()
    for local_node, _ in remote_nodes[1:]:
        await local_node.network.join(first_remote_node_remote)
    await asyncio.sleep(MAINTENANCE_FREQUENCY)

    # Stop random node
    remote_node = choice(remote_nodes)
    remote_nodes.remove(remote_node)
    remote_node_local, remote_node_remote = remote_node[0], remote_node[1]
    await remote_node_local._stop_server()

    # Wait some time for re-stabilizing and check self-corrected network
    await asyncio.sleep(MAINTENANCE_FREQUENCY * 3)
    remote_nodes_remote = list(zip(*remote_nodes))[0]
    for remote_node in remote_nodes_remote:
        remote_network = remote_node.network
        for finger in remote_network.finger_table:
            expected_node = _get_expected_node(finger.start, remote_nodes_remote)
            assert finger.node == expected_node

    await stop_nodes()


def _get_expected_node(id, nodes):
    candidate_nodes = list(filter(lambda n: n.id > id, nodes)) or nodes
    expected_node = reduce(lambda n1, n2: n1 if n1.id < n2.id else n2, candidate_nodes)
    return expected_node
