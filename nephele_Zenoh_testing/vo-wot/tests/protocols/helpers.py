#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import random
import uuid

from faker import Faker
from reactivex.scheduler.eventloop import IOLoopScheduler
from tornado import ioloop

from tests.utils import run_test_coroutine
from wotpy.wot.dictionaries.interaction import PropertyFragmentDict, EventFragmentDict, ActionFragmentDict
from wotpy.wot.td import ThingDescription


def client_test_on_property_change(servient, protocol_client_cls):
    """Helper function to test observation of Property updates on bindings clients."""

    exposed_thing = next(servient.exposed_things)

    prop_name = uuid.uuid4().hex

    exposed_thing.add_property(prop_name, PropertyFragmentDict({
        "type": "string",
        "observable": True
    }), value=Faker().sentence())

    servient.refresh_forms()

    td = ThingDescription.from_thing(exposed_thing.thing)

    async def test_coroutine():
        protocol_client = protocol_client_cls()

        values = [Faker().sentence() for _ in range(10)]
        loop = asyncio.get_running_loop()
        values_observed = {value: loop.create_future() for value in values}

        async def periodic_write_next():
            while True:
                try:
                    next_value = next(val for val, fut in values_observed.items() if not fut.done())
                    await exposed_thing.properties[prop_name].write(next_value)
                except StopIteration:
                    break
                await asyncio.sleep(0.01)

        def on_next(ev):
            prop_value = ev.data.value
            if prop_value in values_observed and not values_observed[prop_value].done():
                values_observed[prop_value].set_result(True)

        observable = protocol_client.on_property_change(td, prop_name)

        loop = ioloop.IOLoop.current()
        scheduler = IOLoopScheduler(loop)
        subscription = observable.subscribe(on_next, scheduler=scheduler)

        task = asyncio.create_task(periodic_write_next())

        await asyncio.gather(*values_observed.values())

        task.cancel()
        subscription.dispose()

    run_test_coroutine(test_coroutine)


def client_test_on_event(servient, protocol_client_cls):
    """Helper function to test observation of Events on bindings clients."""

    exposed_thing = next(servient.exposed_things)

    event_name = uuid.uuid4().hex

    exposed_thing.add_event(event_name, EventFragmentDict({
        "type": "number"
    }))

    servient.refresh_forms()

    td = ThingDescription.from_thing(exposed_thing.thing)

    async def test_coroutine():
        protocol_client = protocol_client_cls()

        payloads = [Faker().pyint() for _ in range(10)]
        loop = asyncio.get_running_loop()
        future_payloads = {key: loop.create_future() for key in payloads}

        async def periodic_emit_next():
            while True:
                try:
                    next_value = next(val for val, fut in future_payloads.items() if not fut.done())
                    exposed_thing.events[event_name].emit(next_value)
                except StopIteration:
                    break
                await asyncio.sleep(0.01)

        def on_next(ev):
            if ev.data in future_payloads and not future_payloads[ev.data].done():
                future_payloads[ev.data].set_result(True)

        observable = protocol_client.on_event(td, event_name)

        loop = ioloop.IOLoop.current()
        scheduler = IOLoopScheduler(loop)
        subscription = observable.subscribe(on_next, scheduler=scheduler)

        task = asyncio.create_task(periodic_emit_next())

        await asyncio.gather(*future_payloads.values())

        task.cancel()
        subscription.dispose()

    run_test_coroutine(test_coroutine)


def client_test_read_property(servient, protocol_client_cls, timeout=None):
    """Helper function to test Property reads on bindings clients."""

    exposed_thing = next(servient.exposed_things)

    prop_name = uuid.uuid4().hex

    exposed_thing.add_property(prop_name, PropertyFragmentDict({
        "type": "string",
        "observable": True
    }), value=Faker().sentence())

    servient.refresh_forms()

    td = ThingDescription.from_thing(exposed_thing.thing)

    async def test_coroutine():
        protocol_client = protocol_client_cls()
        prop_value = Faker().sentence()

        curr_prop_value = await protocol_client.read_property(td, prop_name, timeout=timeout)

        assert curr_prop_value != prop_value

        await exposed_thing.properties[prop_name].write(prop_value)

        curr_prop_value = await protocol_client.read_property(td, prop_name, timeout=timeout)

        assert curr_prop_value == prop_value

    run_test_coroutine(test_coroutine)


def client_test_write_property(servient, protocol_client_cls, timeout=None):
    """Helper function to test Property writes on bindings clients."""

    exposed_thing = next(servient.exposed_things)

    prop_name = uuid.uuid4().hex

    exposed_thing.add_property(prop_name, PropertyFragmentDict({
        "type": "string",
        "observable": True
    }), value=Faker().sentence())

    servient.refresh_forms()

    td = ThingDescription.from_thing(exposed_thing.thing)

    async def test_coroutine():
        protocol_client = protocol_client_cls()
        prop_value = Faker().sentence()

        prev_value = await exposed_thing.properties[prop_name].read()
        assert prev_value != prop_value

        await protocol_client.write_property(td, prop_name, prop_value, timeout=timeout)

        curr_value = await exposed_thing.properties[prop_name].read()
        assert curr_value == prop_value

    run_test_coroutine(test_coroutine)


def client_test_invoke_action(servient, protocol_client_cls, timeout=None):
    """Helper function to test Action invocations on bindings clients."""

    exposed_thing = next(servient.exposed_things)

    action_name = uuid.uuid4().hex

    async def action_handler(parameters):
        input_value = parameters.get("input")
        await asyncio.sleep(random.random() * 0.1)
        return("{:f}".format(input_value))

    exposed_thing.add_action(action_name, ActionFragmentDict({
        "input": {"type": "number"},
        "output": {"type": "string"}
    }), action_handler)

    servient.refresh_forms()

    td = ThingDescription.from_thing(exposed_thing.thing)

    async def test_coroutine():
        protocol_client = protocol_client_cls()

        input_value = Faker().pyint()

        result = await protocol_client.invoke_action(td, action_name, input_value, timeout=timeout)
        result_expected = await action_handler({"input": input_value})

        assert result == result_expected

    run_test_coroutine(test_coroutine)


def client_test_invoke_action_error(servient, protocol_client_cls):
    """Helper function to test Action invocations that raise errors on bindings clients."""

    exposed_thing = next(servient.exposed_things)

    action_name = uuid.uuid4().hex

    err_message = Faker().sentence()

    # noinspection PyUnusedLocal
    def action_handler(parameters):
        raise ValueError(err_message)

    exposed_thing.add_action(action_name, ActionFragmentDict({
        "input": {"type": "number"},
        "output": {"type": "string"}
    }), action_handler)

    servient.refresh_forms()

    td = ThingDescription.from_thing(exposed_thing.thing)

    async def test_coroutine():
        protocol_client = protocol_client_cls()

        try:
            await protocol_client.invoke_action(td, action_name, Faker().pyint())
            raise AssertionError("Did not raise Exception")
        except Exception as ex:
            assert err_message in str(ex)

    run_test_coroutine(test_coroutine)


def client_test_on_property_change_error(servient, protocol_client_cls):
    """Helper function to test propagation of errors raised
    during observation of Property updates on bindings clients."""

    exposed_thing = next(servient.exposed_things)

    prop_name = uuid.uuid4().hex

    exposed_thing.add_property(prop_name, PropertyFragmentDict({
        "type": "string",
        "observable": True
    }), value=Faker().sentence())

    servient.refresh_forms()

    td = ThingDescription.from_thing(exposed_thing.thing)

    async def test_coroutine():
        protocol_client = protocol_client_cls()

        await servient.shutdown()

        loop = asyncio.get_running_loop()
        future_err = loop.create_future()

        # noinspection PyUnusedLocal
        def on_next(item):
            future_err.set_exception(Exception("Should not have emitted any items"))

        def on_error(err):
            future_err.set_result(err)

        observable = protocol_client.on_property_change(td, prop_name)

        loop = ioloop.IOLoop.current()
        scheduler = IOLoopScheduler(loop)
        subscribe_kwargs = {
            "on_next": on_next,
            "on_error": on_error,
            "scheduler": scheduler
        }

        subscription = observable.subscribe(**subscribe_kwargs)

        observe_err = await future_err

        assert isinstance(observe_err, Exception)

        subscription.dispose()

    run_test_coroutine(test_coroutine)
