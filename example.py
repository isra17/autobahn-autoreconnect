import os
import txaio
txaio.use_asyncio()

from autobahn.asyncio.wamp import ApplicationSession
from autobahn_autoreconnect import ApplicationRunner

class MyComponent(ApplicationSession):

    async def onJoin(self, details):
        # listening for the corresponding message from the "backend"
        # (any session that .publish()es to this topic).
        def onevent(msg):
            print("Got event: {}".format(msg))
        await self.subscribe(onevent, 'com.myapp.hello')

        # call a remote procedure.
        res = await self.call('com.myapp.add2', 2, 3)
        print("Got result: {}".format(res))


if __name__ == '__main__':
    runner = ApplicationRunner(
        os.environ.get("AUTOBAHN_DEMO_ROUTER", "ws://localhost:8080/ws"),
        u"realm1",
        debug_app=False,  # optional; log even more details
    )
    runner.run(MyComponent)

