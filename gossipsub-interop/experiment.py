import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Set

import script_instruction
from script_instruction import GossipSubParams, NodeID, ScriptInstruction


@dataclass
class Binary:
    path: str
    percent_of_nodes: int


@dataclass
class ExperimentParams:
    script: List[ScriptInstruction] = field(default_factory=list)


def spread_heartbeat_delay(
    node_count: int,
    template_gs_params: GossipSubParams,
    enable_topic_streams: bool = False,
) -> List[ScriptInstruction]:
    instructions = []
    initial_delay = timedelta(seconds=0.1)
    for i in range(node_count):
        initial_delay += timedelta(milliseconds=0.100)
        gs_params = template_gs_params.model_copy()
        # The value is in nanoseconds
        gs_params.HeartbeatInitialDelay = initial_delay.microseconds * 1_000
        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=i,
                instruction=script_instruction.InitGossipSub(
                    gossipSubParams=gs_params,
                    enableTopicStreams=True if enable_topic_streams else None,
                ),
            )
        )
    return instructions


def partial_message_scenario(
    disable_gossip: bool, node_count: int
) -> List[ScriptInstruction]:
    instructions: List[ScriptInstruction] = []
    gs_params = GossipSubParams()
    if disable_gossip:
        gs_params.Dlazy = 0
        gs_params.GossipFactor = 0
    instructions.extend(spread_heartbeat_delay(node_count, gs_params))

    number_of_conns_per_node = min(20, node_count - 1)
    instructions.extend(random_network_mesh(node_count, number_of_conns_per_node))

    topic = "a-subnet"
    instructions.append(
        script_instruction.SubscribeToTopic(topicID=topic, partial=True)
    )

    groupID = random.randint(0, (2**8) - 1)

    # Wait for some setup time
    elapsed_seconds = 30
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    # Assign random parts to each node
    if node_count == 2:
        # If just two nodes, make sure we can always generate a full message
        part = random.randint(0, 255)
        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=0,
                instruction=script_instruction.AddPartialMessage(
                    topicID=topic, groupID=groupID, parts=part
                ),
            )
        )
        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=1,
                instruction=script_instruction.AddPartialMessage(
                    topicID=topic, groupID=groupID, parts=(0xFF ^ part)
                ),
            )
        )
    else:
        for i in range(node_count):
            parts = random.randint(0, 255)
            instructions.append(
                script_instruction.IfNodeIDEquals(
                    nodeID=i,
                    instruction=script_instruction.AddPartialMessage(
                        topicID=topic, groupID=groupID, parts=parts
                    ),
                )
            )

    # Everyone publishes their partial message. This is how nodes learn about
    # each others parts and can request them.
    instructions.append(
        script_instruction.PublishPartial(topicID=topic, groupID=groupID)
    )

    # Wait for everything to flush
    elapsed_seconds += 10
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    return instructions


def partial_message_chain_scenario(
    disable_gossip: bool, node_count: int
) -> List[ScriptInstruction]:
    instructions: List[ScriptInstruction] = []
    gs_params = GossipSubParams()
    if disable_gossip:
        gs_params.Dlazy = 0
        gs_params.GossipFactor = 0
    instructions.extend(spread_heartbeat_delay(node_count, gs_params))

    # Create a bidirectional chain topology: 0<->1<->2....<->n-1
    # Each node connects to both previous and next (except first and last)
    for i in range(node_count):
        connections = []
        if i < node_count - 1:
            connections.append(i + 1)  # Connect to next

        if connections:
            instructions.append(
                script_instruction.IfNodeIDEquals(
                    nodeID=i,
                    instruction=script_instruction.Connect(connectTo=connections),
                )
            )

    topic = "partial-msg-chain"
    instructions.append(
        script_instruction.SubscribeToTopic(topicID=topic, partial=True)
    )

    # Wait for setup time and mesh stabilization
    elapsed_seconds = 30
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    # 16 messages with 8 parts each
    num_messages = 16
    num_parts = 8

    # Assign parts to nodes in round-robin fashion
    # Each message-part combination goes to exactly one node
    for msg_idx in range(num_messages):
        groupID = msg_idx  # Unique group ID for each message

        # Assign each of the 8 parts to nodes in round-robin
        for part_idx in range(num_parts):
            node_idx = (msg_idx * num_parts + part_idx) % node_count
            part_bitmap = 1 << part_idx  # Single bit for this part

            instructions.append(
                script_instruction.IfNodeIDEquals(
                    nodeID=node_idx,
                    instruction=script_instruction.AddPartialMessage(
                        topicID=topic, groupID=groupID, parts=part_bitmap
                    ),
                )
            )

    # Have multiple nodes with parts for each message try to publish
    # This creates redundancy and ensures the exchange process starts
    for msg_idx in range(num_messages):
        groupID = msg_idx

        elapsed_seconds += 2  # Delay between message groups
        instructions.append(
            script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds)
        )
        instructions.append(
            script_instruction.PublishPartial(topicID=topic, groupID=groupID)
        )

    # Wait for propagation and assembly
    elapsed_seconds += 30
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))
    return instructions


def partial_message_fanout_scenario(
    disable_gossip: bool, node_count: int
) -> List[ScriptInstruction]:
    instructions: List[ScriptInstruction] = []
    gs_params = GossipSubParams()
    if disable_gossip:
        gs_params.Dlazy = 0
        gs_params.GossipFactor = 0
    instructions.extend(spread_heartbeat_delay(node_count, gs_params))

    number_of_conns_per_node = min(20, node_count - 1)
    instructions.extend(random_network_mesh(node_count, number_of_conns_per_node))

    topic = "a-subnet"
    for i in range(node_count):
        # The first node will not subscribe to the topic.
        if i == 0:
            continue

        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=i,
                instruction=script_instruction.SubscribeToTopic(
                    topicID=topic, partial=True
                ),
            )
        )

    groupID = random.randint(0, (2**8) - 1)

    # Wait for some setup time
    elapsed_seconds = 30
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    # First node has everything
    instructions.append(
        script_instruction.IfNodeIDEquals(
            nodeID=0,
            instruction=script_instruction.AddPartialMessage(
                topicID=topic, groupID=groupID, parts=0xFF
            ),
        )
    )

    # First node publishes to a fanout set, here we are saying the first 7 nodes after the publisher
    instructions.append(
        script_instruction.IfNodeIDEquals(
            nodeID=0,
            instruction=script_instruction.PublishPartial(
                topicID=topic,
                groupID=groupID,
                publishToNodeIDs=list(range(1, min(8, node_count))),
            ),
        )
    )

    # Wait for everything to flush
    elapsed_seconds += 10
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    return instructions


def topic_streams_scenario(
    disable_gossip: bool, node_count: int
) -> List[ScriptInstruction]:
    """Exercise the Topic Streams extension.

    See https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/topic-streams.md

    The extension moves topic scoped application messages onto separate long
    lived streams (one per topic, per direction). The motivation is to avoid
    head-of-line blocking between topics: on the single gossipsub stream a large
    message on one topic delays small, latency sensitive messages on another.

    This scenario reproduces that situation. Every node subscribes to two topics:
    a "blob" topic carrying large messages and a "small" topic carrying tiny,
    latency sensitive messages. The two topics are published to concurrently so
    that, without Topic Streams, the small messages would queue behind the large
    blobs. With the extension negotiated, each topic gets its own stream and the
    small messages should not be delayed by the blobs.
    """
    instructions: List[ScriptInstruction] = []
    gs_params = GossipSubParams()
    if disable_gossip:
        gs_params.Dlazy = 0
        gs_params.GossipFactor = 0
    instructions.extend(
        spread_heartbeat_delay(node_count, gs_params, enable_topic_streams=True)
    )

    number_of_conns_per_node = 20
    if number_of_conns_per_node >= node_count:
        number_of_conns_per_node = node_count - 1
    instructions.extend(random_network_mesh(node_count, number_of_conns_per_node))

    blob_topic = "blob-subnet"
    small_topic = "small-msgs"

    # Mock blob validation latency, like the subnet-blob-msg scenario. A column
    # takes around 5ms according to data gathered by lighthouse.
    instructions.append(
        script_instruction.SetTopicValidationDelay(
            topicID=blob_topic, delaySeconds=0.005
        )
    )

    # Every node subscribes to both topics.
    instructions.append(script_instruction.SubscribeToTopic(topicID=blob_topic))
    instructions.append(script_instruction.SubscribeToTopic(topicID=small_topic))

    blob_count = 48
    blob_message_size = 2 * 1024 * blob_count
    small_message_size = 128
    num_rounds = 16

    instructions.extend(
        interleaved_publish_every_12s(
            node_count,
            num_rounds,
            blob_topic=blob_topic,
            blob_message_size=blob_message_size,
            small_topic=small_topic,
            small_message_size=small_message_size,
        )
    )

    return instructions


def scenario(
    scenario_name: str, node_count: int, disable_gossip: bool
) -> ExperimentParams:
    instructions: List[ScriptInstruction] = []
    match scenario_name:
        case "partial-messages":
            instructions = partial_message_scenario(disable_gossip, node_count)
        case "partial-messages-chain":
            instructions = partial_message_chain_scenario(disable_gossip, node_count)
        case "partial-messages-fanout":
            instructions = partial_message_fanout_scenario(disable_gossip, node_count)
        case "subnet-blob-msg":
            gs_params = GossipSubParams()
            if disable_gossip:
                gs_params.Dlazy = 0
                gs_params.GossipFactor = 0
            instructions.extend(spread_heartbeat_delay(node_count, gs_params))

            topic = "a-subnet"
            blob_count = 48
            # According to data gathered by lighthouse, a column takes around
            # 5ms.
            instructions.append(
                script_instruction.SetTopicValidationDelay(
                    topicID=topic, delaySeconds=0.005
                )
            )
            number_of_conns_per_node = 20
            if number_of_conns_per_node >= node_count:
                number_of_conns_per_node = node_count - 1
            instructions.extend(
                random_network_mesh(node_count, number_of_conns_per_node)
            )
            message_size = 2 * 1024 * blob_count
            num_messages = 16
            instructions.append(script_instruction.SubscribeToTopic(topicID=topic))
            instructions.extend(
                random_publish_every_12s(
                    node_count, num_messages, message_size, [topic]
                )
            )
        case "topic-streams":
            instructions = topic_streams_scenario(disable_gossip, node_count)
        case "simple-fanout":
            gs_params = GossipSubParams()
            if disable_gossip:
                gs_params.Dlazy = 0
                gs_params.GossipFactor = 0
            instructions.extend(spread_heartbeat_delay(node_count, gs_params))
            topic_a = "topic-a"
            topic_b = "topic-b"
            number_of_conns_per_node = 20
            if number_of_conns_per_node >= node_count:
                number_of_conns_per_node = node_count - 1
            instructions.extend(
                random_network_mesh(node_count, number_of_conns_per_node)
            )

            # Half nodes will subscribe to topic-a, the other half subscribe to
            # topic-b
            for i in range(node_count):
                if i % 2 == 0:
                    instructions.append(
                        script_instruction.IfNodeIDEquals(
                            nodeID=i,
                            instruction=script_instruction.SubscribeToTopic(
                                topicID=topic_a
                            ),
                        ),
                    )
                else:
                    instructions.append(
                        script_instruction.IfNodeIDEquals(
                            nodeID=i,
                            instruction=script_instruction.SubscribeToTopic(
                                topicID=topic_b
                            ),
                        ),
                    )

            num_messages = 16
            message_size = 1024

            # Every 12s a random node will publish to a random topic
            instructions.extend(
                random_publish_every_12s(
                    node_count, num_messages, message_size, [topic_a, topic_b]
                )
            )

        case _:
            raise ValueError(f"Unknown scenario name: {scenario_name}")

    return ExperimentParams(script=instructions)


IMPLEMENTATIONS: Dict[str, str] = {
    "go": "go-libp2p/gossipsub-bin",
    # Always use debug rust. We don't measure compute performance here.
    "rust": "rust-libp2p/target/debug/rust-libp2p-gossip",
    "nim": "nim-libp2p/gossipsub-bin",
    "jvm": "jvm-libp2p/build/install/jvm-libp2p-gossip/bin/jvm-libp2p-gossip",
}


def composition(impls: List[str]) -> List[Binary]:
    if not impls:
        raise ValueError("composition requires at least one implementation")
    for name in impls:
        if name not in IMPLEMENTATIONS:
            raise ValueError(
                f"Unknown implementation '{name}'. "
                f"Known: {sorted(IMPLEMENTATIONS)}"
            )

    # Split 100% as evenly as possible. First `leftover` impls get +1 (e.g. 3 impls -> 34/33/33).
    base, leftover = divmod(100, len(impls))
    percents = [base + 1] * leftover + [base] * (len(impls) - leftover)

    return [
        Binary(IMPLEMENTATIONS[name], percent_of_nodes=pct)
        for name, pct in zip(impls, percents)
    ]


def random_network_mesh(
    node_count: int, number_of_connections: int
) -> List[ScriptInstruction]:
    connections: Dict[NodeID, Set[NodeID]] = defaultdict(set)
    connect_to: Dict[NodeID, List[NodeID]] = defaultdict(list)
    for node_id in range(node_count):
        while len(connections[node_id]) < number_of_connections:
            target = random.randint(0, node_count - 1)
            if target == node_id:
                continue
            if target in connections[node_id] or node_id in connections[target]:
                continue
            connections[node_id].add(target)
            connections[target].add(node_id)

            connect_to[node_id].append(target)

    instructions = []
    for node_id, node_connections in connect_to.items():
        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=node_id,
                instruction=script_instruction.Connect(
                    connectTo=list(node_connections),
                ),
            )
        )
    return instructions


def random_publish_every_12s(
    node_count: int, num_messages: int, message_size: int, topic_strs: List[str]
) -> List[ScriptInstruction]:
    instructions = []

    # Start at 120 seconds (2 minutes) to allow for setup time
    elapsed_seconds = 120
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    for i in range(num_messages):
        random_node = random.randint(0, node_count - 1)
        topic_str = random.choice(topic_strs)
        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=random_node,
                instruction=script_instruction.Publish(
                    messageID=i,
                    topicID=topic_str,
                    messageSizeBytes=message_size,
                ),
            )
        )
        elapsed_seconds += 12  # Add 12 seconds for each subsequent message
        instructions.append(
            script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds)
        )

    elapsed_seconds += 30  # wait a bit more to allow all messages to flush
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    return instructions


def interleaved_publish_every_12s(
    node_count: int,
    num_rounds: int,
    blob_topic: str,
    blob_message_size: int,
    small_topic: str,
    small_message_size: int,
) -> List[ScriptInstruction]:
    """Publish a large blob and a small message at the same instant each round.

    Each round a random node publishes a large message on ``blob_topic`` and,
    at the same simulated time, another random node publishes a small message on
    ``small_topic``. Publishing them concurrently is what surfaces head-of-line
    blocking on a single stream: the Topic Streams extension is expected to keep
    the small messages flowing independently of the large blobs.

    Message IDs are unique across both topics so the delivery analysis can tell
    them apart: blob messages use even IDs and small messages use odd IDs.
    """
    instructions: List[ScriptInstruction] = []

    # Start at 120 seconds (2 minutes) to allow for setup time
    elapsed_seconds = 120
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    for i in range(num_rounds):
        blob_publisher = random.randint(0, node_count - 1)
        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=blob_publisher,
                instruction=script_instruction.Publish(
                    messageID=2 * i,
                    topicID=blob_topic,
                    messageSizeBytes=blob_message_size,
                ),
            )
        )

        small_publisher = random.randint(0, node_count - 1)
        instructions.append(
            script_instruction.IfNodeIDEquals(
                nodeID=small_publisher,
                instruction=script_instruction.Publish(
                    messageID=2 * i + 1,
                    topicID=small_topic,
                    messageSizeBytes=small_message_size,
                ),
            )
        )

        elapsed_seconds += 12  # Add 12 seconds for each subsequent round
        instructions.append(
            script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds)
        )

    elapsed_seconds += 30  # wait a bit more to allow all messages to flush
    instructions.append(script_instruction.WaitUntil(elapsedSeconds=elapsed_seconds))

    return instructions
