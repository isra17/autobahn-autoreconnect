from setuptools import setup, find_packages

setup(
    name='autobahn-autoreconnect',
    version='0.0.3',

    description='Python Autobahn runner with auto-reconnect feature',
    url='https://github.com/isra17/autobahn-autoreconnect',
    author='isra17',
    author_email='isra017@gmail.com',
    license='LGPL2',

    packages=find_packages(exclude=['contrib', 'docs', 'tests*']),
    install_requires=['autobahn>=0.14.0']
)
