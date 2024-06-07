#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import datetime
import json
import random
import ssl
import uuid
from urllib import parse

import pytest
import tornado.httpclient
from faker import Faker

from tests.utils import find_free_port, run_test_coroutine
from wotpy.protocols.enums import InteractionVerbs
from wotpy.protocols.http.enums import HTTPSchemes
from wotpy.protocols.http.server import HTTPServer
from wotpy.wot.constants import WOT_TD_CONTEXT_URL_V1_1
from wotpy.wot.dictionaries.interaction import PropertyFragmentDict
from wotpy.wot.dictionaries.thing import ThingFragment
from wotpy.wot.exposed.thing import ExposedThing
from wotpy.wot.servient import Servient
from wotpy.wot.thing import Thing

JSON_HEADERS = {"Content-Type": "application/json"}
FORM_URLENCODED_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def _get_property_href(exp_thing, prop_name, server):
    """Helper function to retrieve the Property read/write href."""

    prop = exp_thing.thing.properties[prop_name]
    prop_forms = server.build_forms("localhost", prop)
    return next(item.href for item in prop_forms if InteractionVerbs.READ_PROPERTY in item.op)


def _get_property_observe_href(exp_thing, prop_name, server):
    """Helper function to retrieve the Property subscription href."""

    prop = exp_thing.thing.properties[prop_name]
    prop_forms = server.build_forms("localhost", prop)
    return next(item.href for item in prop_forms if InteractionVerbs.OBSERVE_PROPERTY in item.op)


def _get_action_href(exp_thing, action_name, server):
    """Helper function to retrieve the Property subscription href."""

    action = exp_thing.thing.actions[action_name]
    action_forms = server.build_forms("localhost", action)
    return next(item.href for item in action_forms if InteractionVerbs.INVOKE_ACTION in item.op)


def _get_event_observe_href(exp_thing, event_name, server):
    """Helper function to retrieve the Event subscription href."""

    event = exp_thing.thing.events[event_name]
    event_forms = server.build_forms("localhost", event)
    return next(item.href for item in event_forms if InteractionVerbs.SUBSCRIBE_EVENT in item.op)


def test_property_get(http_server):
    """Properties exposed in an HTTP server can be read with an HTTP GET request."""

    exposed_thing = next(http_server.exposed_things)
    prop_name = next(iter(exposed_thing.thing.properties.keys()))
    href = _get_property_href(exposed_thing, prop_name, http_server)

    async def test_coroutine():
        prop_value = Faker().pyint()
        await exposed_thing.properties[prop_name].write(prop_value)
        http_client = tornado.httpclient.AsyncHTTPClient()
        http_request = tornado.httpclient.HTTPRequest(href, method="GET")
        response = await http_client.fetch(http_request)

        assert json.loads(response.body).get("value") == prop_value

    run_test_coroutine(test_coroutine)


def _test_property_set(server, body, prop_value, headers=None):
    """Helper function to test Property updates over HTTP."""

    exposed_thing = next(server.exposed_things)
    prop_name = next(iter(exposed_thing.thing.properties.keys()))
    href = _get_property_href(exposed_thing, prop_name, server)

    async def test_coroutine():
        http_client = tornado.httpclient.AsyncHTTPClient()
        http_request = tornado.httpclient.HTTPRequest(href, method="PUT", body=body, headers=headers)
        response = await http_client.fetch(http_request)
        value = await exposed_thing.properties[prop_name].read()

        assert response.rethrow() is None
        assert value == prop_value

    run_test_coroutine(test_coroutine)


def test_property_set_form_urlencoded(http_server):
    """Properties exposed in an HTTP server can be
    updated with an application/x-www-form-urlencoded HTTP PUT request."""

    prop_value = Faker().pyint()
    body = parse.urlencode({"value": prop_value})
    _test_property_set(http_server, body, str(prop_value), headers=FORM_URLENCODED_HEADERS)


def test_property_set_json(http_server):
    """Properties exposed in an HTTP server can be
    updated with an application/json HTTP PUT request."""

    prop_value = Faker().pyint()
    body = json.dumps({"value": prop_value})
    _test_property_set(http_server, body, prop_value, headers=JSON_HEADERS)


def test_property_subscribe(http_server):
    """Properties exposed in an HTTP server can be subscribed to with an HTTP GET request."""

    exposed_thing = next(http_server.exposed_things)
    prop_name = next(iter(exposed_thing.thing.properties.keys()))
    href = _get_property_observe_href(exposed_thing, prop_name, http_server)

    init_value = Faker().pyint()
    prop_value = Faker().pyint()

    assert init_value != prop_value

    async def set_property():
        while True:
            await exposed_thing.properties[prop_name].write(prop_value)
            await asyncio.sleep(0.01)

    async def test_coroutine():
        await exposed_thing.properties[prop_name].write(init_value)

        task = asyncio.create_task(set_property())

        http_client = tornado.httpclient.AsyncHTTPClient()
        http_request = tornado.httpclient.HTTPRequest(href, method="GET")
        response = await http_client.fetch(http_request)

        task.cancel()

        result = json.loads(response.body)
        result = result.get("value", result)
        assert result == prop_value

    run_test_coroutine(test_coroutine)


async def _test_action_run(server, action_handler, input_value):
    """Helper to run Action invocation tests."""

    exposed_thing = next(server.exposed_things)
    action_name = next(iter(exposed_thing.thing.actions.keys()))
    href = _get_action_href(exposed_thing, action_name, server)

    exposed_thing.set_action_handler(action_name, action_handler)

    body = json.dumps({"input": input_value})
    http_client = tornado.httpclient.AsyncHTTPClient()
    http_request = tornado.httpclient.HTTPRequest(href, method="POST", body=body, headers=JSON_HEADERS)
    response = await http_client.fetch(http_request)
    result = json.loads(response.body)

    return result


def test_action_run_success(http_server):
    """Actions exposed in an HTTP server can be successfully invoked with an HTTP POST request."""

    async def test_coroutine():
        async def action_handler(parameters):
            return parameters.get("input") * 2

        input_value = Faker().pyint()
        result = await _test_action_run(http_server, action_handler, input_value)

        assert result.get("result") == input_value * 2
        assert result.get("error", None) is None

    run_test_coroutine(test_coroutine)


def test_action_run_error(http_server):
    """Actions exposed in an HTTP server can raise errors."""

    async def test_coroutine():
        async def action_handler(parameters):
            raise Exception(parameters.get("input"))

        ex_message = Faker().sentence()
        result = await _test_action_run(http_server, action_handler, ex_message)

        assert result.get("result", None) is None
        assert ex_message in result.get("error")

    run_test_coroutine(test_coroutine)


def test_event_subscribe(http_server):
    """Events exposed in an HTTP server can be subscribed to with an HTTP GET request."""

    exposed_thing = next(http_server.exposed_things)
    event_name = next(iter(exposed_thing.thing.events.keys()))
    href = _get_event_observe_href(exposed_thing, event_name, http_server)

    fake = Faker()
    payload = {fake.pystr(): random.choice([fake.pystr(), fake.pyint()]) for _ in range(5)}

    async def emit_event():
        while True:
            exposed_thing.emit_event(event_name, payload)
            await asyncio.sleep(0.01)

    async def test_coroutine():
        task = asyncio.create_task(emit_event())

        http_client = tornado.httpclient.AsyncHTTPClient()
        http_request = tornado.httpclient.HTTPRequest(href, method="GET")
        response = await http_client.fetch(http_request)

        task.cancel()

        assert json.loads(response.body).get("payload") == payload

    run_test_coroutine(test_coroutine)


def test_ssl_context(self_signed_ssl_context):
    """An SSL context can be passed to the HTTP server to enable encryption."""

    port = find_free_port()

    thing_fragment = ThingFragment({
        "@context": [
            WOT_TD_CONTEXT_URL_V1_1,
        ],
        "id": uuid.uuid4().urn,
        "title": uuid.uuid4().hex,
        "securityDefinitions": {
            "nosec_sc":{
                "scheme":"nosec"
            }
        },
        "security": "nosec_sc"
    })
    thing = Thing(thing_fragment=thing_fragment)
    exposed_thing = ExposedThing(servient=Servient(), thing=thing)

    prop_name = uuid.uuid4().hex

    exposed_thing.add_property(prop_name, PropertyFragmentDict({
        "type": "string",
        "observable": True
    }), value=Faker().pystr())


    server = HTTPServer(port=port, ssl_context=self_signed_ssl_context)
    server.add_exposed_thing(exposed_thing)

    href = _get_property_href(exposed_thing, prop_name, server)

    assert HTTPSchemes.HTTPS in href

    async def test_coroutine():
        await server.start()

        prop_value = Faker().pystr()
        await exposed_thing.properties[prop_name].write(prop_value)
        http_client = tornado.httpclient.AsyncHTTPClient()

        with pytest.raises(ssl.SSLError):
            await http_client.fetch(tornado.httpclient.HTTPRequest(href, method="GET"))

        http_request = tornado.httpclient.HTTPRequest(href, method="GET", validate_cert=False)
        response = await http_client.fetch(http_request)

        result = json.loads(response.body)
        result = result.get("value", result)
        assert result == prop_value

        await server.stop()

    run_test_coroutine(test_coroutine)
