from setuptools import setup, find_packages

setup(
    name='autobahn-autoreconnect',
    version='0.0.1',

    description='Python Autobahn runner with auto-reconnect feature',
    url='https://github.com/isra17/autobahn-autoreconnect',
    author='isra17',
    author_email='isra017@gmail.com',
    license='LGPL2',

    packages=find_packages(exclude=['contrib', 'docs', 'tests*']),
    install_requires=['autobahn==0.10.5'],
    dependency_links=['https://github.com/tavendo/AutobahnPython/archive/3bcbc00382a9d601fe4565216d4e7dc737d5f65e.zip#egg=autobahn-0.10.5']
)
