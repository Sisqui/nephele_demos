#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import json
import time
import uuid
from asyncio import TimeoutError
import random

import pytest
from faker import Faker
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_2, QOS_0

from tests.protocols.mqtt.broker import is_test_broker_online, BROKER_SKIP_REASON, get_test_broker_url
from tests.utils import run_test_coroutine
from wotpy.protocols.enums import InteractionVerbs
from wotpy.protocols.mqtt.handlers.action import ActionMQTTHandler
from wotpy.protocols.mqtt.server import MQTTServer
from wotpy.wot.dictionaries.interaction import PropertyFragmentDict, ActionFragmentDict

pytestmark = pytest.mark.skipif(is_test_broker_online() is False, reason=BROKER_SKIP_REASON)


def build_topic(server, interaction, interaction_verb):
    """Returns the topic for the given interaction and verb."""

    forms = server.build_forms(None, interaction)
    form = next(item for item in forms if interaction_verb == item.op)
    return "/".join(form.href.split("/")[3:])


async def connect_broker(topics):
    """Connects to the test MQTT broker and subscribes to the topics."""

    topics = [(topics, QOS_0)] if isinstance(topics, str) else topics

    amqtt_client = MQTTClient()
    await amqtt_client.connect(get_test_broker_url())
    await amqtt_client.subscribe(topics)

    return amqtt_client


async def _ping(mqtt_server, timeout=None):
    """Returns True if the given MQTT server has answered to a PING request."""

    broker_url = get_test_broker_url()

    topic_ping = "{}/ping".format(mqtt_server.servient_id)
    topic_pong = "{}/pong".format(mqtt_server.servient_id)

    try:
        amqtt_client = MQTTClient()
        await amqtt_client.connect(broker_url)
        await amqtt_client.subscribe([(topic_pong, QOS_2)])
        bytes_payload = bytes(uuid.uuid4().hex, "utf8")
        await amqtt_client.publish(topic_ping, bytes_payload, qos=QOS_2)
        message = await amqtt_client.deliver_message(timeout=timeout)
        assert message.data == bytes_payload
        await amqtt_client.disconnect()
    except TimeoutError:
        return False

    return True


DEFAULT_PING_TIMEOUT = 1.0


def test_start_stop():
    """The MQTT server may be started and stopped."""

    mqtt_server = MQTTServer(broker_url=get_test_broker_url())

    async def test_coroutine():
        assert not (await _ping(mqtt_server, timeout=DEFAULT_PING_TIMEOUT))

        await mqtt_server.start()

        assert (await _ping(mqtt_server))
        assert (await _ping(mqtt_server))

        await mqtt_server.stop()
        await mqtt_server.start()
        await mqtt_server.stop()

        assert not (await _ping(mqtt_server, timeout=DEFAULT_PING_TIMEOUT))

        await mqtt_server.stop()
        await mqtt_server.start()
        await mqtt_server.start()

        assert (await _ping(mqtt_server))

    run_test_coroutine(test_coroutine)


def test_servient_id():
    """An MQTT server may be identified by a unique Servient ID to avoid topic collisions."""

    broker_url = get_test_broker_url()

    mqtt_srv_01 = MQTTServer(broker_url=broker_url)
    mqtt_srv_02 = MQTTServer(broker_url=broker_url)
    mqtt_srv_03 = MQTTServer(broker_url=broker_url, servient_id=Faker().pystr())

    assert mqtt_srv_01.servient_id and mqtt_srv_02.servient_id and mqtt_srv_03.servient_id
    assert mqtt_srv_01.servient_id == mqtt_srv_02.servient_id
    assert mqtt_srv_01.servient_id != mqtt_srv_03.servient_id

    async def assert_ping_loop(srv, num_iters=10):
        for _ in range(num_iters):
            assert (await _ping(srv, timeout=DEFAULT_PING_TIMEOUT))
            await asyncio.sleep(random.uniform(0.1, 0.3))

    async def test_coroutine():
        await mqtt_srv_01.start()
        await mqtt_srv_03.start()

        await assert_ping_loop(mqtt_srv_01)
        await assert_ping_loop(mqtt_srv_03)

    run_test_coroutine(test_coroutine)


def test_property_read(mqtt_server):
    """Current Property values may be requested using the MQTT binding."""

    exposed_thing = next(mqtt_server.exposed_things)
    prop_name = next(iter(exposed_thing.thing.properties.keys()))
    prop = exposed_thing.thing.properties[prop_name]
    topic_read = build_topic(mqtt_server, prop, InteractionVerbs.READ_PROPERTY)
    topic_observe = build_topic(mqtt_server, prop, InteractionVerbs.OBSERVE_PROPERTY)

    observe_timeout_secs = 1.0

    async def test_coroutine():
        prop_value = await exposed_thing.properties[prop_name].read()

        client_read = await connect_broker(topic_read)
        client_observe = await connect_broker(topic_observe)

        try:
            await client_observe.deliver_message(timeout=observe_timeout_secs)
            raise AssertionError('Unexpected message on topic {}'.format(topic_observe))
        except TimeoutError:
            pass

        async def read_value():
            while True:
                payload = json.dumps({"action": "read"}).encode()
                await client_read.publish(topic_read, payload, qos=QOS_2)
                await asyncio.sleep(0.05)

        task = asyncio.create_task(read_value())

        msg = await client_observe.deliver_message()

        task.cancel()

        assert json.loads(msg.data.decode()).get("value") == prop_value

    run_test_coroutine(test_coroutine)


def test_property_write(mqtt_server):
    """Property values may be updated using the MQTT binding."""

    exposed_thing = next(mqtt_server.exposed_things)
    prop_name = next(iter(exposed_thing.thing.properties.keys()))
    prop = exposed_thing.thing.properties[prop_name]
    topic_write = build_topic(mqtt_server, prop, InteractionVerbs.WRITE_PROPERTY)
    topic_observe = build_topic(mqtt_server, prop, InteractionVerbs.OBSERVE_PROPERTY)

    async def test_coroutine():
        updated_value = Faker().sentence()

        client_write = await connect_broker(topic_write)
        client_observe = await connect_broker(topic_observe)

        loop = asyncio.get_running_loop()
        future_observe = loop.create_future()

        async def resolve_future_on_update():
            msg_observe = await client_observe.deliver_message()
            assert json.loads(msg_observe.data.decode()).get("value") == updated_value
            future_observe.set_result(True)

        asyncio.create_task(resolve_future_on_update())

        async def publish_write():
            while True:
                payload = json.dumps({"action": "write", "value": updated_value}).encode()
                await client_write.publish(topic_write, payload, qos=QOS_2)
                await asyncio.sleep(0.05)

        task = asyncio.create_task(publish_write())

        await future_observe

        assert future_observe.result() is True

        task.cancel()

    run_test_coroutine(test_coroutine)


CALLBACK_MS = 50


@pytest.mark.parametrize("mqtt_server", [{"property_callback_ms": CALLBACK_MS}], indirect=True)
def test_property_add_remove(mqtt_server):
    """The MQTT binding reacts appropriately to Properties
    being added and removed from ExposedThings."""

    exposed_thing = next(mqtt_server.exposed_things)
    prop_names = list(exposed_thing.thing.properties.keys())

    for name in prop_names:
        exposed_thing.remove_property(name)

    broker_url = mqtt_server._broker_url
    def add_prop(pname):
        exposed_thing.add_property(pname, PropertyFragmentDict({
            "type": "number",
            "observable": True
        }), value=Faker().pyint())

    def del_prop(pname):
        exposed_thing.remove_property(pname)

    async def is_prop_active(prop, timeout_secs=1.0):
        topic_observe = build_topic(mqtt_server, prop, InteractionVerbs.OBSERVE_PROPERTY)
        topic_write = build_topic(mqtt_server, prop, InteractionVerbs.WRITE_PROPERTY)

        client_observe = await connect_broker(topic_observe)
        client_write = await connect_broker(topic_write)

        value = Faker().pyint()

        async def publish_write():
            while True:
                payload = json.dumps({"action": "write", "value": value}).encode()
                await client_write.publish(topic_write, payload, qos=QOS_0)
                await asyncio.sleep(timeout_secs / 4)

        task = asyncio.create_task(publish_write())

        try:
            msg = await client_observe.deliver_message(timeout=timeout_secs)
            assert json.loads(msg.data.decode()).get("value") == value
            return True
        except TimeoutError:
            return False
        finally:
            task.cancel()

    async def test_coroutine():
        sleep_secs = (CALLBACK_MS / 1000.0) * 4

        prop_01_name = uuid.uuid4().hex
        prop_02_name = uuid.uuid4().hex
        prop_03_name = uuid.uuid4().hex

        add_prop(prop_01_name)
        add_prop(prop_02_name)
        add_prop(prop_03_name)

        prop_01 = exposed_thing.thing.properties[prop_01_name]
        prop_02 = exposed_thing.thing.properties[prop_02_name]
        prop_03 = exposed_thing.thing.properties[prop_03_name]

        await asyncio.sleep(sleep_secs)

        assert (await is_prop_active(prop_01))
        assert (await is_prop_active(prop_02))
        assert (await is_prop_active(prop_03))

        del_prop(prop_01_name)

        assert not (await is_prop_active(prop_01))
        assert (await is_prop_active(prop_02))
        assert (await is_prop_active(prop_03))

        del_prop(prop_03_name)

        assert not (await is_prop_active(prop_01))
        assert (await is_prop_active(prop_02))
        assert not (await is_prop_active(prop_03))

        add_prop(prop_01_name)

        prop_01 = exposed_thing.thing.properties[prop_01_name]

        assert (await is_prop_active(prop_01))
        assert (await is_prop_active(prop_02))
        assert not (await is_prop_active(prop_03))

    run_test_coroutine(test_coroutine)


def test_observe_property_changes(mqtt_server):
    """Property updates may be observed using the MQTT binding."""

    exposed_thing = next(mqtt_server.exposed_things)
    prop_name = next(iter(exposed_thing.thing.properties.keys()))
    prop = exposed_thing.thing.properties[prop_name]
    topic_observe = build_topic(mqtt_server, prop, InteractionVerbs.OBSERVE_PROPERTY)

    async def test_coroutine():
        client_observe = await connect_broker(topic_observe)

        updated_value = Faker().sentence()

        async def write_value():
            while True:
                await exposed_thing.properties[prop_name].write(updated_value)
                await asyncio.sleep(0.05)

        task = asyncio.create_task(write_value())

        msg = await client_observe.deliver_message()

        assert json.loads(msg.data.decode()).get("value") == updated_value

        task.cancel()

    run_test_coroutine(test_coroutine)


def test_observe_event(mqtt_server):
    """Events may be observed using the MQTT binding."""

    now_ms = int(time.time() * 1000)

    exposed_thing = next(mqtt_server.exposed_things)
    event_name = next(iter(exposed_thing.thing.events.keys()))
    event = exposed_thing.thing.events[event_name]
    topic = build_topic(mqtt_server, event, InteractionVerbs.SUBSCRIBE_EVENT)

    async def test_coroutine():
        client = await connect_broker(topic)

        emitted_value = Faker().pyint()

        async def emit_value():
            while True:
                exposed_thing.events[event_name].emit(emitted_value)
                await asyncio.sleep(0.05)

        task = asyncio.create_task(emit_value())

        msg = await client.deliver_message()

        event_data = json.loads(msg.data.decode())

        assert event_data.get("name") == event_name
        assert event_data.get("data") == emitted_value
        assert event_data.get("timestamp") >= now_ms

        task.cancel()

    run_test_coroutine(test_coroutine)


def test_action_invoke(mqtt_server):
    """Actions can be invoked using the MQTT binding."""

    exposed_thing = next(mqtt_server.exposed_things)
    action_name = next(iter(exposed_thing.thing.actions.keys()))
    action = exposed_thing.thing.actions[action_name]

    topic_invoke = build_topic(mqtt_server, action, InteractionVerbs.INVOKE_ACTION)
    topic_result = ActionMQTTHandler.to_result_topic(topic_invoke)

    async def test_coroutine():
        client_invoke = await connect_broker(topic_invoke)
        client_result = await connect_broker(topic_result)

        data = {
            "id": uuid.uuid4().hex,
            "input": Faker().pyint()
        }

        now_ms = int(time.time() * 1000)

        await client_invoke.publish(topic_invoke, json.dumps(data).encode(), qos=QOS_2)

        msg = await client_result.deliver_message()
        msg_data = json.loads(msg.data.decode())

        assert msg_data.get("id") == data.get("id")
        assert msg_data.get("result") == "{:f}".format(data.get("input"))
        assert msg_data.get("timestamp") >= now_ms

    run_test_coroutine(test_coroutine)


def test_action_invoke_error(mqtt_server):
    """Action errors are handled appropriately by the MQTT binding."""

    exposed_thing = next(mqtt_server.exposed_things)

    action_name = uuid.uuid4().hex
    err_message = Faker().sentence()

    # noinspection PyUnusedLocal
    def handler(parameters):
        raise TypeError(err_message)

    broker_url = mqtt_server._broker_url
    servient_id = mqtt_server.servient_id
    thing_name = exposed_thing.thing.title
    exposed_thing.add_action(action_name, ActionFragmentDict({
        "input": {"type": "string"},
        "output": {"type": "string"}
    }), handler)

    action = exposed_thing.thing.actions[action_name]

    topic_invoke = build_topic(mqtt_server, action, InteractionVerbs.INVOKE_ACTION)
    topic_result = ActionMQTTHandler.to_result_topic(topic_invoke)

    async def test_coroutine():
        client_invoke = await connect_broker(topic_invoke)
        client_result = await connect_broker(topic_result)

        data = {
            "id": uuid.uuid4().hex,
            "input": Faker().pyint()
        }

        await client_invoke.publish(topic_invoke, json.dumps(data).encode(), qos=QOS_2)

        msg = await client_result.deliver_message()
        msg_data = json.loads(msg.data.decode())

        assert msg_data.get("id") == data.get("id")
        assert msg_data.get("error") == err_message
        assert msg_data.get("result", None) is None

    run_test_coroutine(test_coroutine)


def test_action_invoke_parallel(mqtt_server):
    """Multiple Actions can be invoked in parallel using the MQTT binding."""

    exposed_thing = next(mqtt_server.exposed_things)
    action_name = next(iter(exposed_thing.thing.actions.keys()))
    action = exposed_thing.thing.actions[action_name]

    topic_invoke = build_topic(mqtt_server, action, InteractionVerbs.INVOKE_ACTION)
    topic_result = ActionMQTTHandler.to_result_topic(topic_invoke)

    num_requests = 10

    async def test_coroutine():
        client_invoke = await connect_broker(topic_invoke)
        client_result = await connect_broker(topic_result)

        requests = []

        for idx in range(num_requests):
            requests.append({
                "id": uuid.uuid4().hex,
                "input": Faker().pyint()
            })

        now_ms = int(time.time() * 1000)

        for idx in range(num_requests):
            await client_invoke.publish(topic_invoke, json.dumps(requests[idx]).encode(), qos=QOS_2)

        for idx in range(num_requests):
            msg = await client_result.deliver_message()
            msg_data = json.loads(msg.data.decode())
            expected = next(item for item in requests if item.get("id") == msg_data.get("id"))

            assert msg_data.get("id") == expected.get("id")
            assert msg_data.get("result") == "{:f}".format(expected.get("input"))
            assert msg_data.get("timestamp") >= now_ms

    run_test_coroutine(test_coroutine)
