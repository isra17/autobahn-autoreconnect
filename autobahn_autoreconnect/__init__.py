# coding=utf-8
###############################################################################
#
# The MIT License (MIT)
#
# Original work Copyright (c) Tavendo GmbH
# Modified work Copyright 2016 Israël Hallé
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

import signal

from autobahn.wamp import protocol
from autobahn.wamp.types import ComponentConfig
try:
    from autobahn.websocket.protocol import parseWsUrl
except:
    from autobahn.websocket.util import parse_url as parseWsUrl
from autobahn.asyncio.websocket import WampWebSocketClientFactory

import asyncio
import txaio

txaio.use_asyncio()

class ExceededRetryCount(Exception):
    pass

class IReconnectStrategy(object):
    def get_retry_interval(self):
        raise NotImplementedError('get_retry_interval')

    def reset_retry_interval(self):
        raise NotImplementedError('reset_retry_interval')

    def increase_retry_interval(self):
        raise NotImplementedError('increase_retry_interval')

    def retry(self):
        raise NotImplementedError('retry')


class NoRetryStrategy(IReconnectStrategy):
    def reset_retry_interval(self):
        pass

    def retry(self):
        return False


class BackoffStrategy(IReconnectStrategy):
    def __init__(self, initial_interval=0.5, max_interval=512, factor=2):
        self._initial_interval = initial_interval
        self._retry_interval = initial_interval
        self._max_interval = max_interval
        self._factor = factor

    def get_retry_interval(self):
        return self._retry_interval

    def reset_retry_interval(self):
        self._retry_interval = self._initial_interval

    def increase_retry_interval(self):
        self._retry_interval *= self._factor

    def retry(self):
        return self._retry_interval <= self._max_interval


class ApplicationRunner(object):
    """
    This class is a slightly modified version of autobahn.asyncio.wamp.ApplicationRunner
    with auto reconnection feature to with customizable strategies.
    """

    def __init__(self, url, realm, extra=None, serializers=None, debug_app=False,
                 ssl=None, loop=None, retry_strategy=BackoffStrategy(), open_handshake_timeout=30, auto_ping_interval=10, auto_ping_timeout=27):
        """
        :param url: The WebSocket URL of the WAMP router to connect to (e.g. `ws://somehost.com:8090/somepath`)
        :type url: unicode
        :param realm: The WAMP realm to join the application session to.
        :type realm: unicode
        :param extra: Optional extra configuration to forward to the application component.
        :type extra: dict
        :param serializers: A list of WAMP serializers to use (or None for default serializers).
           Serializers must implement :class:`autobahn.wamp.interfaces.ISerializer`.
        :type serializers: list
        :param debug_app: Turn on app-level debugging.
        :type debug_app: bool
        :param ssl: An (optional) SSL context instance or a bool. See
           the documentation for the `loop.create_connection` asyncio
           method, to which this value is passed as the ``ssl=``
           kwarg.
        :type ssl: :class:`ssl.SSLContext` or bool
        :param open_handshake_timeout: How long to wait for the opening handshake to complete (in seconds).
        :param auto_ping_interval: How often to send a keep-alive ping to the router (in seconds).
           A value of None turns off pings.
        :type auto_ping_interval: int
        :param auto_ping_timeout: Consider the connection dropped if the router does not respond to our
           ping for more than X seconds.
        :type auto_ping_timeout: int
        """
        self._url = url
        self._realm = realm
        self._extra = extra or dict()
        self._debug_app = debug_app
        self._serializers = serializers
        self._loop = loop or asyncio.get_event_loop()
        self._retry_strategy = retry_strategy
        self._closing = False
        self._open_handshake_timeout = open_handshake_timeout
        self._auto_ping_interval = auto_ping_interval
        self._auto_ping_timeout = auto_ping_timeout

        self._isSecure, self._host, self._port, _, _, _ = parseWsUrl(url)

        if ssl is None:
            self._ssl = self._isSecure
        else:
            if ssl and not self._isSecure:
                raise RuntimeError(
                    'ssl argument value passed to %s conflicts with the "ws:" '
                    'prefix of the url argument. Did you mean to use "wss:"?' %
                    self.__class__.__name__)
            self._ssl = ssl


    def run(self, make):
        """
        Run the application component.
        :param make: A factory that produces instances of :class:`autobahn.asyncio.wamp.ApplicationSession`
           when called with an instance of :class:`autobahn.wamp.types.ComponentConfig`.
        :type make: callable
        """

        def _create_app_session():
            cfg = ComponentConfig(self._realm, self._extra)
            try:
                session = make(cfg)
            except Exception as e:
                # the app component could not be created .. fatal
                asyncio.get_event_loop().stop()
                raise e
            else:
                session.debug_app = self._debug_app
                return session

        self._transport_factory = WampWebSocketClientFactory(_create_app_session, url=self._url, serializers=self._serializers)

        if self._auto_ping_interval is not None and self._auto_ping_timeout is not None:
            self._transport_factory.setProtocolOptions(openHandshakeTimeout=self._open_handshake_timeout, autoPingInterval=self._auto_ping_interval, autoPingTimeout=self._auto_ping_timeout)

        txaio.use_asyncio()
        txaio.config.loop = self._loop

        asyncio.async(self._connect(), loop=self._loop)

        try:
            self._loop.add_signal_handler(signal.SIGTERM, self.stop)
        except NotImplementedError:
             # Ignore if not implemented. Means this program is running in windows.
            pass

        try:
            self._loop.run_forever()
        except KeyboardInterrupt:
            # wait until we send Goodbye if user hit ctrl-c
            # (done outside this except so SIGTERM gets the same handling)
            pass

        self._closing = True

        if self._active_protocol and self._active_protocol._session:
            self._loop.run_until_complete(self._active_protocol._session.leave())
        self._loop.close()

    @asyncio.coroutine
    def _connect(self):
        self._active_protocol = None
        self._retry_strategy.reset_retry_interval()
        while True:
            try:
                _, protocol = yield from self._loop.create_connection(self._transport_factory, self._host, self._port, ssl=self._ssl)
                protocol.is_closed.add_done_callback(self._reconnect)
                self._active_protocol = protocol
                return
            except OSError:
                print('Connection failed')
                if self._retry_strategy.retry():
                    retry_interval = self._retry_strategy.get_retry_interval()
                    print('Retry in {} seconds'.format(retry_interval))
                    yield from asyncio.sleep(retry_interval)
                else:
                    print('Exceeded retry count')
                    self._loop.stop()
                    raise ExceededRetryCount()

                self._retry_strategy.increase_retry_interval()

    def _reconnect(self, f):
        # Reconnect
        print('Connection lost')
        if not self._closing:
            print('Reconnecting')
            asyncio.async(self._connect(), loop=self._loop)

    def stop(self, *args):
        self._loop.stop()

