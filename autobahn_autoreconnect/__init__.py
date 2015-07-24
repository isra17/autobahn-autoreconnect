import signal

from autobahn.wamp import protocol
from autobahn.wamp.types import ComponentConfig
from autobahn.websocket.protocol import parseWsUrl
from autobahn.asyncio.websocket import WampWebSocketClientFactory

import asyncio
import txaio

txaio.use_asyncio()

__all__ = (
    'ApplicationRunner'
)

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

    def __init__(self, url, realm, extra=None, serializers=None,
                 debug=False, debug_wamp=False, debug_app=False,
                 ssl=None, loop=None, retry_strategy=BackoffStrategy()):
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
        :param debug: Turn on low-level debugging.
        :type debug: bool
        :param debug_wamp: Turn on WAMP-level debugging.
        :type debug_wamp: bool
        :param debug_app: Turn on app-level debugging.
        :type debug_app: bool
        :param ssl: An (optional) SSL context instance or a bool. See
           the documentation for the `loop.create_connection` asyncio
           method, to which this value is passed as the ``ssl=``
           kwarg.
        :type ssl: :class:`ssl.SSLContext` or bool
        """
        self._url = url
        self._realm = realm
        self._extra = extra or dict()
        self._debug = debug
        self._debug_wamp = debug_wamp
        self._debug_app = debug_app
        self._make = None
        self._serializers = serializers
        self._loop = loop or asyncio.get_event_loop()
        self._retry_strategy = retry_strategy

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

        transport_factory = WampWebSocketClientFactory(_create_app_session, url=self._url, serializers=self._serializers,
                                                       debug=self._debug, debug_wamp=self._debug_wamp)

        txaio.use_asyncio()
        txaio.config.loop = self._loop

        protocol = self._loop.run_until_complete(self._connect(transport_factory))
        self._loop.add_signal_handler(signal.SIGTERM, self.stop)

        try:
            self._loop.run_forever()
        except KeyboardInterrupt:
            # wait until we send Goodbye if user hit ctrl-c
            # (done outside this except so SIGTERM gets the same handling)
            pass

        if protocol._session:
            self._loop.run_until_complete(protocol._session.leave())
        self._loop.close()

    @asyncio.coroutine
    def _connect(self, transport_factory):
        self._retry_strategy.reset_retry_interval()
        while True:
            try:
                _, protocol = yield from self._loop.create_connection(transport_factory, self._host, self._port, ssl=self._ssl)
                protocol.is_closed.add_done_callback(self._closed)
                return protocol
            except OSError:
                if self._retry_strategy.retry():
                    retry_interval = self._retry_strategy.get_retry_interval()
                    print('Connection failed, retry in {} seconds'.format(retry_interval))
                    yield from asyncio.sleep(retry_interval)
                    self._retry_strategy.increase_retry_interval()
                else:
                    print('Connection failed, exceeded retry count')
                    raise ExceededRetryCount()

    def _closed(self, f):
        # Reconnect
        print('_closed')

    def stop(self):
        self._loop.stop()
