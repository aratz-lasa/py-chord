import random
from functools import reduce

from .abc import INode, IChordNetwork, ID_LENGTH
from .errors import NetworkCrash

CHORD_PORT = 6666
MAX_NODES = 2 ** ID_LENGTH
FINGER_AMOUNT = ID_LENGTH
MAINTENANCE_FREQUENCY = 2
TIMEOUT = 1


class Finger:
    def __init__(self):
        self.node = None
        self.start = None
        self.end = None


class ChordNetwork(IChordNetwork):
    def __init__(self, node: INode):
        self.node = node
        self.finger_table = [Finger() for _ in range(FINGER_AMOUNT)]
        for index, finger in enumerate(self.finger_table):
            finger.start = (self.node.id + (2 ** index)) % MAX_NODES
            finger.end = (self.node.id + (2 ** (index + 1)) - 1) % MAX_NODES

    async def join(self, node: INode = None) -> None:
        if node and await node._is_alive():
            await self._init_finger_table(node)
            predecessor = await self._find_predecessor(self.node.id)
            await self.node._set_predecessor(predecessor)
            await self._update_others()

        else:  # It is the only node in the network
            for finger in self.finger_table:
                finger.node = self.node
            predecessor = await self._find_predecessor(self.node.id)
            await self.node._set_predecessor(predecessor)

    async def mantain(self) -> None:
        # Remove dead fingers
        await self._remove_dead_fingers()
        # Stabilize
        await self.stabilize()
        # Fix fingers
        await self.fix_fingers()
        # Update predecessor
        predecessor = await self._find_predecessor(self.node.id)
        if await predecessor._is_alive():
            self.node._predecessor = predecessor
        else:
            self.node._predecessor = None
        # Check if node is isolated
        if not filter(lambda f: f.node, self.finger_table
                      ):  # There is no alive successor or finger
            raise NetworkCrash()

    async def stabilize(self):
        successor = await self.node._get_successor()
        if successor == self.node:
            raise NetworkCrash()
        old_predecessor = await successor._get_predecessor()
        if await old_predecessor._is_alive() and is_between_ids(
                old_predecessor.id, self.node.id, successor.id):
            successor = old_predecessor
            await self.node._set_successor(old_predecessor)
        await successor._notify(self.node)

    async def fix_fingers(
            self
    ):  # Different from pseudo-code, for speeding up, the original is '_original_fix_fingers'
        for i, finger in enumerate(self.finger_table):
            successor = await self.node._find_successor(finger.start)
            if await successor._is_alive():
                finger.node = successor
            else:
                finger.node = None

    def remove_left_node(self, node: INode):
        for finger in filter(lambda f: f.node.id == node.id,
                             self.finger_table):
            finger.node = None

    async def _original_fix_fingers(self):
        random_index = random.choice([i for i in range(1, FINGER_AMOUNT)
                                      ])  # Random index > 1
        self.finger_table[random_index].node = await self.node._find_successor(
            self.finger_table[random_index].start)

    async def _find_predecessor(self, id: int) -> INode:
        predecessor = self.node
        predecessor_successor = await predecessor._get_successor()
        while not is_between_ids(
                id, predecessor.id, predecessor_successor.id,
                second_equality=True):
            old_predecessor = predecessor
            predecessor = await predecessor._closest_preceding_finger(id)
            if not await predecessor._is_alive():
                predecessor = old_predecessor
            if old_predecessor == predecessor:
                break  # It is the first node in the Network
            predecessor_successor = await predecessor._get_successor()
        return predecessor

    async def _init_finger_table(self, node: INode) -> None:
        self.finger_table[0].node = await node._find_successor(
            self.finger_table[0].start)
        predecessor = await (await
                             self.node._get_successor())._get_predecessor()
        await predecessor._set_predecessor(self.node)
        for i in range(FINGER_AMOUNT - 1):
            finger = self.finger_table[i]
            plus_one_finger = self.finger_table[i + 1]
            if is_between_ids(plus_one_finger.start,
                              self.node.id,
                              finger.node.id,
                              first_equality=True):
                plus_one_finger.node = finger.node
            else:
                recommeded_successor = await node._find_successor(
                    plus_one_finger.start)
                plus_one_finger.node = closest_successor(
                    plus_one_finger.start, self.node, recommeded_successor)

    async def _update_others(self) -> None:
        for i in range(FINGER_AMOUNT):
            id = self.node.id - (2 ** i)
            if id < 0:
                id = MAX_NODES + id
            predecessor = await self._find_predecessor(
                id)  # Not to try with negatives
            await predecessor._update_finger_table(self.node, i)

    async def _remove_dead_fingers(self):
        for finger in self.finger_table:
            if finger.node and not await finger.node._is_alive():
                self.remove_left_node(finger.node)

    def _distance_between_ids(self, id1, id2):
        if id2 - id1 >= 0:
            return id2 - id1
        return MAX_NODES - (id2 - id1)


def closest_successor(id: int, *nodes: INode):
    candidate_nodes = list(filter(lambda n: n.id > id, nodes)) or nodes
    return reduce(lambda n1, n2: n1 if n1.id < n2.id else n2, candidate_nodes)


def is_between_ids(middle_id: int,
                   first_id: int,
                   second_id: int,
                   first_equality: bool = False,
                   second_equality: bool = False) -> bool:
    if first_equality and middle_id == first_id:
        return True
    if second_equality and middle_id == second_id:
        return True
    if first_id < second_id:
        return first_id < middle_id < second_id
    return not second_id <= middle_id <= first_id
