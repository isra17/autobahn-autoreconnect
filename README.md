# autobahn-autoreconnect
Python Autobahn runner with auto-reconnect feature

## Installation
```bash
$pip install autobahn-autoreconnect 
```

## Dependencies
autobahn >= 14.0.0

## Usage
Just import the `ApplicationRunner` from `autobahn_autoreconnect` and it works as a drop in replacement for
`autobahn.asyncio.wamp.Application Runner`.

```python
from autobahn.asyncio.wamp import ApplicationSession
# from autobahn.asyncio.wamp import ApplicationRunner
from autobahn_autoreconnect import ApplicationRunner


class MyComponent(ApplicationSession):
    # awsesome wamp stuff 
  
if __name__ == '__main__':
    runner = ApplicationRunner("ws://localhost:8080/ws", "realm1")
    runner.run(MyComponent)
```

### Retry Strategy
The default retry strategy is the `BackoffStrategy` based on an increasing time interval starting at 0.5 seconds and doubling 
until a maximum of 512 seconds before giving up. If you want to override the defaults you can pass in your own `BackoffStrategy` like so:

```python
from autobahn_autoreconnect import BackoffStrategy

# start with a 10s delay and increase by a factor of 10 until 1000s
# This strategy will wait 10s, 100s and 1000s and then stop retrying
strategy = BackoffStrategy(initial_interval=10, max_interval=1000 factor=10)
runner = ApplicationRunner("ws://localhost:8080/ws", "realm1", retry_strategy=strategy)
```

### Custom Retry Strategies
You can also implement you own retry class by inheriting from `autobahn_autoreconnect.IReconnectStrategy`.

For example, to retry every second for 100 seconds we could do something like:

```python
from autobahn_autoreconnect import IReconnectStrategy

class OneSecondStrategy(IReconnectStrategy):

    def __init__(self):
        self._retry_counter = 0
  
    def get_retry_interval(self):
        """Return interval, in seconds, to wait between retries"""
        return 1 

    def reset_retry_interval(self):
        """Called before the first time we try to reconnect"""
        self._retry_counter = 0

    def increase_retry_interval(self):
        """Called every time a retry attempt fails"""
        self._retry_counter += 1
    
    def retry(self):
        """Returning True will keep retrying, False will stop retrying"""
        return self._retry_counter < 100
        
runner = ApplicationRunner("ws://localhost:8080/ws", "realm1", retry_strategy=OneSecondStrategy())
```
