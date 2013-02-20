#!/usr/bin/env python
import os
from distutils.core import setup

execfile(os.path.join('ljbackup', 'release.py'))

setup(
    name='LJBackup',
    version=version,
    description='The Flexo Livejournal Backup thing!',
    author='Nick Murdoch',
    author_email='ljbackup' + '@nivan.net',
    url='https://github.com/flexo/ljbackup',
    packages=['ljbackup'],
)
